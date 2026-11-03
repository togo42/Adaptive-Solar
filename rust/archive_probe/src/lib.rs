//! Optional CPython host experiment. Every uncertainty returns None; Python
//! remains the authoritative reader and error producer. No archive writes.
use flate2::read::MultiGzDecoder;
use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyTuple};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::ffi::{c_char, c_double, c_int, CStr, CString};
use std::fs::{self, File};
use std::io::Read;
use std::path::Path;
use std::sync::{Arc, Mutex};

const HARD_PAGE_BYTES: usize = 4 * 1024 * 1024;
const HARD_EVENT_BYTES: usize = 1024 * 1024;
const MAX_INTEGER: i64 = i64::MAX;
const ADD_DOT_ZERO: c_int = 0x02;

thread_local! {
    // Raw protocol 1 keeps its existing None/error behavior. A source-wide
    // projection must additionally preserve Python exceptions dispatched by
    // signal handlers during CPython's numeric conversion routines.
    static PROJECTION_ERROR: RefCell<Option<Option<PyErr>>> = const { RefCell::new(None) };
}

struct ProjectionErrorScope;

impl ProjectionErrorScope {
    fn start() -> Option<Self> {
        PROJECTION_ERROR.with(|state| {
            let mut slot = state.borrow_mut();
            if slot.is_some() {
                None
            } else {
                *slot = Some(None);
                Some(Self)
            }
        })
    }

    fn take(&self) -> Option<PyErr> {
        PROJECTION_ERROR.with(|state| state.borrow_mut().as_mut().and_then(Option::take))
    }
}

impl Drop for ProjectionErrorScope {
    fn drop(&mut self) {
        PROJECTION_ERROR.with(|state| *state.borrow_mut() = None);
    }
}

// CPython's own decimal conversion and repr, rather than a Rust approximation
// of the archive's Python JSON float formatting. This is intentionally cp314,
// not a limited-ABI or non-CPython extension.
unsafe extern "C" {
    fn PyOS_string_to_double(
        text: *const c_char,
        end: *mut *mut c_char,
        overflow_exception: *mut ffi::PyObject,
    ) -> c_double;
    fn PyOS_double_to_string(
        value: c_double,
        format: c_char,
        precision: c_int,
        flags: c_int,
        kind: *mut c_int,
    ) -> *mut c_char;
}

fn clear_python_error() {
    // Every exported operation holds Python's GIL.
    unsafe {
        PROJECTION_ERROR.with(|state| {
            let mut slot = state.borrow_mut();
            if let Some(captured) = slot.as_mut() {
                if !ffi::PyErr_Occurred().is_null() {
                    let error = PyErr::fetch(Python::assume_attached());
                    if captured.is_none() {
                        *captured = Some(error);
                    }
                }
            } else {
                ffi::PyErr_Clear();
            }
        });
    }
}

fn sha(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

/// Reject duplicate/reserved keys before serde's arbitrary-precision private
/// number representation can conflate an original object with a number.
/// String literals are skipped structurally; serde validates the full grammar.
fn audit_shape(raw: &[u8], max_depth: usize) -> Option<()> {
    let mut stack: Vec<Option<HashSet<String>>> = Vec::new();
    let mut i = 0;
    while i < raw.len() {
        match raw[i] {
            b'{' => {
                stack.push(Some(HashSet::new()));
                if stack.len() > max_depth {
                    return None;
                }
            }
            b'[' => {
                stack.push(None);
                if stack.len() > max_depth {
                    return None;
                }
            }
            b'}' => {
                if stack.pop()?.is_none() {
                    return None;
                }
            }
            b']' => {
                if stack.pop()?.is_some() {
                    return None;
                }
            }
            b'"' => {
                let start = i;
                i += 1;
                loop {
                    match *raw.get(i)? {
                        b'\\' => {
                            i += 2;
                        }
                        b'"' => break,
                        _ => i += 1,
                    }
                }
                let end = i + 1;
                let mut next = end;
                while raw.get(next).is_some_and(u8::is_ascii_whitespace) {
                    next += 1;
                }
                if raw.get(next) == Some(&b':') {
                    let key: String = serde_json::from_slice(&raw[start..end]).ok()?;
                    if key == "$serde_json::private::Number" {
                        return None;
                    }
                    if !stack.last_mut()?.as_mut()?.insert(key) {
                        return None;
                    }
                }
            }
            _ => {}
        }
        i += 1;
    }
    stack.is_empty().then_some(())
}

fn number_bytes(text: &str) -> Option<Vec<u8>> {
    let source = CString::new(text).ok()?;
    unsafe {
        if text.bytes().any(|b| matches!(b, b'.' | b'e' | b'E')) {
            let mut end = std::ptr::null_mut();
            let value = PyOS_string_to_double(source.as_ptr(), &mut end, std::ptr::null_mut());
            if !ffi::PyErr_Occurred().is_null()
                || end != source.as_ptr().add(text.len()).cast_mut()
                || !value.is_finite()
            {
                clear_python_error();
                return None;
            }
            let encoded =
                PyOS_double_to_string(value, b'r' as c_char, 0, ADD_DOT_ZERO, std::ptr::null_mut());
            if encoded.is_null() {
                clear_python_error();
                return None;
            }
            let output = CStr::from_ptr(encoded).to_bytes().to_vec();
            ffi::PyMem_Free(encoded.cast());
            Some(output)
        } else {
            // Both parsing and decimal string conversion obey this interpreter's
            // active int_max_str_digits, including the unlimited setting.
            let mut end = std::ptr::null_mut();
            let integer = ffi::PyLong_FromString(source.as_ptr(), &mut end, 10);
            if integer.is_null() {
                clear_python_error();
                return None;
            }
            let rendered = ffi::PyObject_Str(integer);
            ffi::Py_DecRef(integer);
            if rendered.is_null() {
                clear_python_error();
                return None;
            }
            let mut length = 0;
            let pointer = ffi::PyUnicode_AsUTF8AndSize(rendered, &mut length);
            if pointer.is_null() {
                ffi::Py_DecRef(rendered);
                clear_python_error();
                return None;
            }
            let output = std::slice::from_raw_parts(pointer.cast::<u8>(), length as usize).to_vec();
            ffi::Py_DecRef(rendered);
            Some(output)
        }
    }
}

struct Encoder {
    numbers: HashMap<String, Vec<u8>>,
}

impl Encoder {
    fn new() -> Self {
        Self {
            numbers: HashMap::new(),
        }
    }

    fn string(out: &mut Vec<u8>, value: &str) {
        out.push(b'"');
        for byte in value.bytes() {
            match byte {
                b'"' => out.extend_from_slice(b"\\\""),
                b'\\' => out.extend_from_slice(b"\\\\"),
                8 => out.extend_from_slice(b"\\b"),
                9 => out.extend_from_slice(b"\\t"),
                10 => out.extend_from_slice(b"\\n"),
                12 => out.extend_from_slice(b"\\f"),
                13 => out.extend_from_slice(b"\\r"),
                0..=31 => out.extend_from_slice(format!("\\u{byte:04x}").as_bytes()),
                _ => out.push(byte),
            }
        }
        out.push(b'"');
    }

    fn write(
        &mut self,
        out: &mut Vec<u8>,
        value: &Value,
        limit: usize,
        without_sha: bool,
    ) -> Option<()> {
        match value {
            Value::Null => out.extend_from_slice(b"null"),
            Value::Bool(true) => out.extend_from_slice(b"true"),
            Value::Bool(false) => out.extend_from_slice(b"false"),
            Value::String(value) => Self::string(out, value),
            Value::Number(value) => {
                let text = value.to_string();
                if !self.numbers.contains_key(&text) {
                    self.numbers.insert(text.clone(), number_bytes(&text)?);
                }
                out.extend_from_slice(self.numbers.get(&text)?);
            }
            Value::Array(values) => {
                out.push(b'[');
                for (i, item) in values.iter().enumerate() {
                    if i != 0 {
                        out.push(b',');
                    }
                    self.write(out, item, limit, false)?;
                }
                out.push(b']');
            }
            Value::Object(values) => {
                out.push(b'{');
                let mut first = true;
                // serde_json's default map is ordered by Unicode/UTF-8 keys;
                // preserve_order is deliberately not enabled.
                for (key, item) in values {
                    if without_sha && key == "sha256" {
                        continue;
                    }
                    if !first {
                        out.push(b',');
                    }
                    first = false;
                    Self::string(out, key);
                    out.push(b':');
                    self.write(out, item, limit, false)?;
                }
                out.push(b'}');
            }
        }
        (out.len() <= limit).then_some(())
    }

    fn encode(&mut self, value: &Value, limit: usize, without_sha: bool) -> Option<Vec<u8>> {
        let mut out = Vec::new();
        self.write(&mut out, value, limit, without_sha)?;
        Some(out)
    }
}

fn object<'a>(value: &'a Value, keys: &[&str]) -> Option<&'a Map<String, Value>> {
    let item = value.as_object()?;
    (item.len() == keys.len() && keys.iter().all(|k| item.contains_key(*k))).then_some(item)
}

fn integer(value: &Value, low: i64) -> Option<i64> {
    let text = value.as_number()?.to_string();
    if text.contains(['.', 'e', 'E']) {
        return None;
    }
    let parsed = text.parse::<i64>().ok()?;
    (parsed >= low).then_some(parsed)
}

fn text(value: &Value, maximum: usize) -> Option<&str> {
    let value = value.as_str()?;
    let whitespace = |byte: u8| matches!(byte, 9..=13 | 28..=32);
    if !value.is_ascii()
        || value.is_empty()
        || value.len() > maximum
        || whitespace(*value.as_bytes().first()?)
        || whitespace(*value.as_bytes().last()?)
    {
        return None;
    }
    Some(value)
}

fn generation(value: &Value) -> Option<&str> {
    let value = value.as_str()?;
    (value.len() == 36
        && value.bytes().enumerate().all(|(i, b)| {
            if matches!(i, 8 | 13 | 18 | 23) {
                b == b'-'
            } else {
                b.is_ascii_digit() || (b'a'..=b'f').contains(&b)
            }
        }))
    .then_some(value)
}

fn utc_parts(value: &Value) -> Option<[u32; 7]> {
    let value = value.as_str()?.as_bytes();
    if !(value.len() == 25 || value.len() == 32) || &value[value.len() - 6..] != b"+00:00" {
        return None;
    }
    for (i, expected) in [(4, b'-'), (7, b'-'), (10, b'T'), (13, b':'), (16, b':')] {
        if value[i] != expected {
            return None;
        }
    }
    if value.len() == 32 && (value[19] != b'.' || !value[20..26].iter().all(u8::is_ascii_digit)) {
        return None;
    }
    let digits = |a: usize, b: usize| -> Option<u32> {
        let slice = &value[a..b];
        if !slice.iter().all(u8::is_ascii_digit) {
            return None;
        }
        std::str::from_utf8(slice).ok()?.parse().ok()
    };
    let year = digits(0, 4)?;
    let month = digits(5, 7)?;
    let day = digits(8, 10)?;
    let days = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) {
                29
            } else {
                28
            }
        }
        _ => return None,
    };
    let hour = digits(11, 13)?;
    let minute = digits(14, 16)?;
    let second = digits(17, 19)?;
    (year > 0 && day > 0 && day <= days && hour < 24 && minute < 60 && second < 60).then_some([
        year,
        month,
        day,
        hour,
        minute,
        second,
        if value.len() == 32 {
            digits(20, 26)?
        } else {
            0
        },
    ])
}

fn utc_stamp(value: &Value) -> Option<()> {
    utc_parts(value).map(|_| ())
}

fn cursor(value: &Value) -> Option<Option<(&str, i64)>> {
    if value.is_null() {
        return Some(None);
    }
    let raw = value.as_str()?;
    let (gen, seq) = raw.split_once(':')?;
    generation(&Value::String(gen.into()))?;
    if seq.is_empty() || seq.len() > 19 || !seq.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    Some(Some((gen, seq.parse().ok()?)))
}

fn validate(
    value: &Value,
    max_page: usize,
    max_event: usize,
    max_events: usize,
) -> Option<Vec<usize>> {
    let wrapper = object(
        value,
        &[
            "schema",
            "source",
            "ingest_order",
            "stored_at",
            "archive_started_at",
            "page",
        ],
    )?;
    if integer(&wrapper["schema"], 0)? != 1 {
        return None;
    }
    text(&wrapper["source"], 256)?;
    integer(&wrapper["ingest_order"], 1)?;
    utc_stamp(&wrapper["stored_at"])?;
    utc_stamp(&wrapper["archive_started_at"])?;
    let page_value = &wrapper["page"];
    let page = object(
        page_value,
        &[
            "schema",
            "generation",
            "oldest_sequence",
            "requested_cursor",
            "next_cursor",
            "events",
            "gap",
        ],
    )?;
    if integer(&page["schema"], 0)? != 1 {
        return None;
    }
    let gen = generation(&page["generation"])?;
    let oldest = integer(&page["oldest_sequence"], 1)?;
    let request = cursor(&page["requested_cursor"])?;
    let (next_gen, next_seq) = cursor(&page["next_cursor"])??;
    if next_gen != gen {
        return None;
    }
    let events = page["events"].as_array()?;
    if events.len() > max_events {
        return None;
    }
    let mut encoder = Encoder::new();
    encoder.encode(page_value, max_page, false)?;
    let start = request.filter(|(g, _)| *g == gen).map_or(0, |(_, s)| s);
    let reason = if request.is_some_and(|(g, _)| g != gen) {
        Some("generation_changed")
    } else if start < oldest - 1 {
        Some("retention_or_overflow")
    } else {
        None
    };
    match reason {
        None => {
            if !page["gap"].is_null() {
                return None;
            }
        }
        Some(reason) => {
            let gap = object(&page["gap"], &["reason", "from", "to"])?;
            if gap["reason"].as_str()? != reason
                || integer(&gap["from"], 0)? != start.checked_add(1)?
                || integer(&gap["to"], 0)? != oldest - 1
            {
                return None;
            }
        }
    }
    let mut previous = start.max(oldest - 1);
    let mut canonical_lengths = Vec::with_capacity(events.len());
    for event in events {
        let envelope = object(
            event,
            &[
                "schema",
                "generation",
                "sequence",
                "event_id",
                "kind",
                "received_at",
                "payload",
                "sha256",
            ],
        )?;
        if integer(&envelope["schema"], 0)? != 1 {
            return None;
        }
        let event_gen = generation(&envelope["generation"])?;
        let sequence = integer(&envelope["sequence"], 1)?;
        text(&envelope["event_id"], 256)?;
        text(&envelope["kind"], 128)?;
        utc_stamp(&envelope["received_at"])?;
        envelope["payload"].as_object()?;
        let canonical = encoder.encode(event, max_page + 65536, true)?;
        if envelope["sha256"].as_str()? != sha(&canonical) {
            return None;
        }
        canonical_lengths.push(encoder.encode(event, max_event, false)?.len());
        if event_gen != gen || sequence != previous.checked_add(1)? {
            return None;
        }
        previous = sequence;
    }
    (next_seq == previous && next_seq <= MAX_INTEGER).then_some(canonical_lengths)
}

struct ValidatedOriginal {
    raw: Vec<u8>,
    value: Value,
    canonical_lengths: Vec<usize>,
}

fn read_validated(
    path: &Path,
    max_page: usize,
    max_event: usize,
    max_events: usize,
    max_depth: usize,
) -> Option<ValidatedOriginal> {
    if max_page == 0
        || max_page > HARD_PAGE_BYTES
        || max_event == 0
        || max_event > HARD_EVENT_BYTES
        || max_events == 0
        || max_events > 1000
        || max_depth == 0
        || max_depth > 64
    {
        return None;
    }
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    if fs::symlink_metadata(path).ok()?.file_type().is_symlink()
        || fs::symlink_metadata(parent).ok()?.file_type().is_symlink()
    {
        return None;
    }
    let file = File::open(path).ok()?;
    let meta = file.metadata().ok()?;
    if !meta.is_file() || meta.len() > (max_page + 65536) as u64 {
        return None;
    }
    let mut raw = Vec::new();
    MultiGzDecoder::new(file)
        .take((max_page + 65537) as u64)
        .read_to_end(&mut raw)
        .ok()?;
    if raw.len() > max_page + 65536 {
        return None;
    }
    let name = path.file_name()?.to_str()?.strip_suffix(".json.gz")?;
    if sha(&raw) != name {
        return None;
    }
    audit_shape(&raw, max_depth)?;
    let value: Value = serde_json::from_slice(&raw).ok()?;
    let canonical_lengths = validate(&value, max_page, max_event, max_events)?;
    Some(ValidatedOriginal {
        raw,
        value,
        canonical_lengths,
    })
}

fn read_impl(
    path: &Path,
    max_page: usize,
    max_event: usize,
    max_events: usize,
    max_depth: usize,
) -> Option<Vec<u8>> {
    read_validated(path, max_page, max_event, max_events, max_depth).map(|original| original.raw)
}

#[pyfunction(signature = (path, max_page_bytes, max_event_bytes, max_page_events, max_depth=64))]
fn read_original<'py>(
    py: Python<'py>,
    path: &str,
    max_page_bytes: usize,
    max_event_bytes: usize,
    max_page_events: usize,
    max_depth: usize,
) -> Option<Bound<'py, PyBytes>> {
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        read_impl(
            Path::new(path),
            max_page_bytes,
            max_event_bytes,
            max_page_events,
            max_depth,
        )
    }))
    .ok()
    .flatten();
    clear_python_error();
    result.map(|raw| PyBytes::new(py, &raw))
}

type Stamp = [u32; 7];

struct ProjectionQuery {
    source: String,
    start: Stamp,
    end: Stamp,
    periods: Vec<(Stamp, Stamp)>,
    anchors: HashSet<String>,
    query_sha256: String,
    bindings_sha256: String,
}

impl ProjectionQuery {
    fn parse(raw: &[u8], max_depth: usize) -> Option<Self> {
        if raw.len() > 1024 * 1024 {
            return None;
        }
        audit_shape(raw, max_depth)?;
        let value: Value = serde_json::from_slice(raw).ok()?;
        let row = object(
            &value,
            &[
                "schema",
                "source",
                "target_start",
                "target_end",
                "periods",
                "bindings_sha256",
            ],
        )?;
        if integer(&row["schema"], 0)? != 1 {
            return None;
        }
        let source = text(&row["source"], 256)?.to_owned();
        let start = utc_parts(&row["target_start"])?;
        let end = utc_parts(&row["target_end"])?;
        if start >= end || start[4..].iter().any(|v| *v != 0) || end[4..].iter().any(|v| *v != 0) {
            return None;
        }
        let binding_hash = row["bindings_sha256"].as_str()?;
        if binding_hash.len() != 64
            || !binding_hash
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return None;
        }
        let inputs = row["periods"].as_array()?;
        if inputs.len() > 1024 {
            return None;
        }
        let mut periods = Vec::with_capacity(inputs.len());
        let mut anchors = HashSet::new();
        for item in inputs {
            let period = object(item, &["valid_from", "valid_to", "config_event_id"])?;
            let a = utc_parts(&period["valid_from"])?;
            let b = utc_parts(&period["valid_to"])?;
            if a >= b {
                return None;
            }
            periods.push((a, b));
            anchors.insert(period["config_event_id"].as_str()?.to_owned());
        }
        let query_sha256 = sha(&Encoder::new().encode(&value, 1024 * 1024, false)?);
        Some(Self {
            source,
            start,
            end,
            periods,
            anchors,
            query_sha256,
            bindings_sha256: binding_hash.to_owned(),
        })
    }

    fn relevant(&self, event: &Value) -> Option<bool> {
        let payload = event.get("payload")?.as_object()?;
        match event.get("kind")?.as_str()? {
            "qualified_interval" => Some(
                utc_parts(payload.get("start")?)? < self.end
                    && utc_parts(payload.get("end")?)? > self.start,
            ),
            "forecast_issued" => {
                if self.anchors.contains(event.get("event_id")?.as_str()?) {
                    return Some(true);
                }
                let stamp = utc_parts(payload.get("issued_at")?)?;
                Some(self.periods.iter().any(|(a, b)| *a <= stamp && stamp < *b))
            }
            _ => Some(false),
        }
    }
}

struct ConfigurationData {
    canonical: Vec<u8>,
    reference: Vec<u8>,
    original_full_working_size: usize,
    anchor: bool,
    original_batch_sha256: String,
    event_id: String,
    received_at: String,
    issued_at: String,
    computed_at: String,
}

impl ConfigurationData {
    fn memory(&self) -> usize {
        self.canonical.capacity()
            + self.reference.capacity()
            + self.original_batch_sha256.capacity()
            + self.event_id.capacity()
            + self.received_at.capacity()
            + self.issued_at.capacity()
            + self.computed_at.capacity()
            + 256
    }
}

/// Only the validating Rust factory can create this immutable capability.
#[pyclass(frozen, weakref, module = "_archive_probe")]
struct VerifiedConfiguration {
    data: Arc<ConfigurationData>,
}

#[pymethods]
impl VerifiedConfiguration {
    #[getter]
    fn configuration_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.data.canonical)
    }

    #[getter]
    fn reference_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.data.reference)
    }

    #[getter]
    fn original_full_working_size(&self) -> usize {
        self.data.original_full_working_size
    }
    #[getter]
    fn anchor(&self) -> bool {
        self.data.anchor
    }
    #[getter]
    fn original_batch_sha256(&self) -> &str {
        &self.data.original_batch_sha256
    }

    fn __contains__(&self, key: &str) -> bool {
        matches!(
            key,
            "kind" | "received_at" | "event_id" | "payload" | "issued_at" | "computed_at"
        )
    }

    fn __getitem__(slf: PyRef<'_, Self>, key: &str, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let value = match key {
            "kind" => "forecast_issued",
            "received_at" => &slf.data.received_at,
            "event_id" => &slf.data.event_id,
            "issued_at" => &slf.data.issued_at,
            "computed_at" => &slf.data.computed_at,
            "payload" => return Ok(slf.into_pyobject(py)?.into_any().unbind()),
            _ => return Err(pyo3::exceptions::PyKeyError::new_err(key.to_owned())),
        };
        Ok(value.into_pyobject(py)?.into_any().unbind())
    }

    #[pyo3(signature = (key, default=None))]
    fn get(
        slf: PyRef<'_, Self>,
        key: &str,
        default: Option<Py<PyAny>>,
        py: Python<'_>,
    ) -> PyResult<Py<PyAny>> {
        if slf.__contains__(key) {
            Self::__getitem__(slf, key, py)
        } else {
            Ok(default.unwrap_or_else(|| py.None()))
        }
    }
}

#[derive(Clone)]
enum ProjectionItem {
    Interval(Vec<u8>),
    Configuration(Arc<ConfigurationData>),
}

#[pyclass(frozen, module = "_archive_probe")]
struct VerifiedQualitySource {
    items: Mutex<Option<Vec<ProjectionItem>>>,
    selected_events: usize,
    source: String,
    query_sha256: String,
    bindings_sha256: String,
    original_files: usize,
    original_events: usize,
    retained_bytes: usize,
}

impl VerifiedQualitySource {
    // Construction is entirely native and unpublished until full validation.
    fn pending(&mut self) -> &mut Vec<ProjectionItem> {
        self.items
            .get_mut()
            .expect("unpublished source mutex")
            .as_mut()
            .expect("unpublished source items")
    }
}

fn item_to_python(py: Python<'_>, item: ProjectionItem) -> PyResult<Py<PyAny>> {
    Ok(match item {
        ProjectionItem::Interval(value) => PyBytes::new(py, &value).into_any().unbind(),
        ProjectionItem::Configuration(value) => {
            Py::new(py, VerifiedConfiguration { data: value })?.into_any()
        }
    })
}

/// Consumes only already validated selected items. No constructor is exported.
#[pyclass(frozen, module = "_archive_probe")]
struct VerifiedQualityItems {
    items: Mutex<std::vec::IntoIter<ProjectionItem>>,
}

#[pymethods]
impl VerifiedQualityItems {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&self, py: Python<'_>) -> PyResult<Option<Py<PyAny>>> {
        // Release the mutex before Python allocations (and possible callbacks).
        let item = self
            .items
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("items mutex poisoned"))?
            .next();
        item.map(|value| item_to_python(py, value)).transpose()
    }

    fn __len__(&self) -> PyResult<usize> {
        Ok(self
            .items
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("items mutex poisoned"))?
            .len())
    }

    fn close(&self) -> PyResult<()> {
        let remaining = {
            let mut items = self
                .items
                .lock()
                .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("items mutex poisoned"))?;
            std::mem::replace(&mut *items, Vec::new().into_iter())
        };
        drop(remaining);
        Ok(())
    }
}

#[pymethods]
impl VerifiedQualitySource {
    fn items<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        // Compatibility inspection only: measured consumers use take_items().
        // Never hold a Rust mutex while invoking Python allocation callbacks.
        let snapshot = self
            .items
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("source mutex poisoned"))?
            .as_ref()
            .ok_or_else(|| {
                pyo3::exceptions::PyRuntimeError::new_err("source items already consumed")
            })?
            .clone();
        let out = snapshot
            .into_iter()
            .map(|item| item_to_python(py, item))
            .collect::<PyResult<Vec<_>>>()?;
        PyTuple::new(py, out)
    }

    fn take_items(&self, py: Python<'_>) -> PyResult<Py<VerifiedQualityItems>> {
        let items = self
            .items
            .lock()
            .map_err(|_| pyo3::exceptions::PyRuntimeError::new_err("source mutex poisoned"))?
            .take()
            .ok_or_else(|| {
                pyo3::exceptions::PyRuntimeError::new_err("source items already consumed")
            })?;
        Py::new(
            py,
            VerifiedQualityItems {
                items: Mutex::new(items.into_iter()),
            },
        )
    }

    #[getter]
    fn source(&self) -> &str {
        &self.source
    }
    #[getter]
    fn query_sha256(&self) -> &str {
        &self.query_sha256
    }
    #[getter]
    fn bindings_sha256(&self) -> &str {
        &self.bindings_sha256
    }
    #[getter]
    fn original_files(&self) -> usize {
        self.original_files
    }
    #[getter]
    fn original_events(&self) -> usize {
        self.original_events
    }
    #[getter]
    fn selected_events(&self) -> usize {
        self.selected_events
    }
    #[getter]
    fn retained_bytes(&self) -> usize {
        self.retained_bytes
    }
}

fn original_reference(event: &Value, source: &str) -> Option<Map<String, Value>> {
    let mut reference = Map::new();
    for (key, value) in event.as_object()? {
        if key != "payload" {
            reference.insert(key.clone(), value.clone());
        }
    }
    reference.insert("source".into(), Value::String(source.into()));
    Some(reference)
}

fn working_size(canonical_event_len: usize, source: &str) -> Option<usize> {
    let mut suffix = vec![b','];
    Encoder::string(&mut suffix, "source");
    suffix.push(b':');
    Encoder::string(&mut suffix, source);
    canonical_event_len.checked_add(suffix.len())
}

fn configuration(
    event: &Value,
    source: &str,
    batch_sha: &str,
    canonical_event_len: usize,
    anchor: bool,
) -> Option<Arc<ConfigurationData>> {
    let payload = event.get("payload")?.as_object()?;
    // Existing native reconstruction remains authoritative for chunked payloads.
    if payload.contains_key("payload_ref") {
        return None;
    }
    let issued = payload.get("issued_at")?;
    let computed = payload.get("computed_at").unwrap_or(issued);
    let received = event.get("received_at")?;
    if !(utc_parts(issued)? <= utc_parts(computed)? && utc_parts(computed)? <= utc_parts(received)?)
    {
        return None;
    }
    let site = payload.get("site")?;
    let producer = payload.get("software")?.get("source_sha256")?;
    let producer_hash = producer.as_str()?;
    if producer_hash.len() != 64
        || !producer_hash
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return None;
    }
    let reference = Value::Object(original_reference(event, source)?);
    let mut encoder = Encoder::new();
    let site_sha = sha(&encoder.encode(site, HARD_EVENT_BYTES, false)?);
    let mut value = Map::new();
    value.insert(
        "schema".into(),
        Value::String("verified-original-forecast-configuration-v1".into()),
    );
    value.insert("original".into(), reference.clone());
    value.insert("dependencies".into(), Value::Array(vec![]));
    value.insert("issued_at".into(), issued.clone());
    value.insert("computed_at".into(), computed.clone());
    value.insert("site_sha256".into(), Value::String(site_sha));
    value.insert("producer_sha256".into(), producer.clone());
    value.insert(
        "anchor_site".into(),
        if anchor { site.clone() } else { Value::Null },
    );
    Some(Arc::new(ConfigurationData {
        canonical: encoder.encode(&Value::Object(value), HARD_EVENT_BYTES + 65536, false)?,
        reference: encoder.encode(&reference, HARD_EVENT_BYTES, false)?,
        original_full_working_size: working_size(canonical_event_len, source)?,
        anchor,
        original_batch_sha256: batch_sha.into(),
        event_id: event.get("event_id")?.as_str()?.into(),
        received_at: received.as_str()?.into(),
        issued_at: issued.as_str()?.into(),
        computed_at: computed.as_str()?.into(),
    }))
}

fn project_quality_source_impl(
    py: Python<'_>,
    paths: Vec<String>,
    query_json: &[u8],
    max_page_bytes: usize,
    max_event_bytes: usize,
    max_page_events: usize,
    max_depth: usize,
    max_retained_bytes: usize,
    max_selected_events: usize,
) -> PyResult<Option<VerifiedQualitySource>> {
    if paths.len() > 50000
        || max_retained_bytes > 536870912
        || max_selected_events > 500000
        || max_retained_bytes == 0
        || max_selected_events == 0
        || max_depth == 0
        || max_depth > 64
        || paths.iter().any(|p| p.len() > 4096)
    {
        return Ok(None);
    }
    let Some(query) = ProjectionQuery::parse(query_json, max_depth) else {
        return Ok(None);
    };
    let mut result = VerifiedQualitySource {
        items: Mutex::new(Some(Vec::new())),
        selected_events: 0,
        source: query.source.clone(),
        query_sha256: query.query_sha256.clone(),
        bindings_sha256: query.bindings_sha256.clone(),
        original_files: 0,
        original_events: 0,
        retained_bytes: 0,
    };
    let mut seen: HashSet<(Arc<str>, i64)> = HashSet::new();
    let mut generations: HashMap<String, Arc<str>> = HashMap::new();
    let mut item_memory = 0usize;
    let path_memory: usize = paths.iter().map(|p| p.capacity() + 32).sum();
    for path in &paths {
        py.check_signals()?;
        // Reserve a conservative bound for one bounded decoded/validated batch;
        // persistent item/key allocations below are counted separately.
        let memory = item_memory
            .saturating_add(result.pending().capacity() * 64)
            .saturating_add(seen.capacity() * 64)
            .saturating_add(generations.len() * 256)
            .saturating_add(path_memory)
            .saturating_add(max_page_bytes.saturating_mul(72));
        if memory > max_retained_bytes {
            return Ok(None);
        }
        let Some(original) = read_validated(
            Path::new(path),
            max_page_bytes,
            max_event_bytes,
            max_page_events,
            max_depth,
        ) else {
            clear_python_error();
            return Ok(None);
        };
        if original.value.get("source").and_then(Value::as_str) != Some(query.source.as_str()) {
            return Ok(None);
        }
        result.original_files += 1;
        let Some(events) = original
            .value
            .get("page")
            .and_then(|p| p.get("events"))
            .and_then(Value::as_array)
        else {
            return Ok(None);
        };
        let batch = Path::new(path)
            .file_name()
            .and_then(|p| p.to_str())
            .and_then(|p| p.strip_suffix(".json.gz"))
            .unwrap_or("");
        for (event, canonical_len) in events.iter().zip(original.canonical_lengths.iter()) {
            result.original_events += 1;
            if result.original_events > 2000000 {
                return Ok(None);
            }
            let Some(gen) = event.get("generation").and_then(Value::as_str) else {
                return Ok(None);
            };
            let interned = generations
                .entry(gen.to_owned())
                .or_insert_with(|| Arc::from(gen))
                .clone();
            let Some(sequence) = event.get("sequence").and_then(|v| integer(v, 1)) else {
                return Ok(None);
            };
            // Source is fixed and checked on every wrapper. Dedup precedes all
            // kind/time predicates, including otherwise irrelevant originals.
            if !seen.insert((interned, sequence)) {
                continue;
            }
            let memory = item_memory
                .saturating_add(result.pending().capacity() * 64)
                .saturating_add(seen.capacity() * 64)
                .saturating_add(generations.len() * 256)
                .saturating_add(path_memory)
                .saturating_add(max_page_bytes.saturating_mul(72));
            if memory > max_retained_bytes {
                return Ok(None);
            }
            let Some(relevant) = query.relevant(event) else {
                return Ok(None);
            };
            if !relevant {
                continue;
            }
            if result.pending().len() >= max_selected_events {
                return Ok(None);
            }
            let item = if event.get("kind").and_then(Value::as_str) == Some("forecast_issued") {
                let anchor = event
                    .get("event_id")
                    .and_then(Value::as_str)
                    .is_some_and(|id| query.anchors.contains(id));
                let Some(proof) =
                    configuration(event, &query.source, batch, *canonical_len, anchor)
                else {
                    return Ok(None);
                };
                result.retained_bytes = result.retained_bytes.saturating_add(proof.canonical.len());
                item_memory = item_memory.saturating_add(proof.memory());
                ProjectionItem::Configuration(proof)
            } else {
                let Some(mut value) = event.as_object().cloned() else {
                    return Ok(None);
                };
                value.insert("source".into(), Value::String(query.source.clone()));
                let Some(bytes) =
                    Encoder::new().encode(&Value::Object(value), max_retained_bytes, false)
                else {
                    return Ok(None);
                };
                result.retained_bytes = result.retained_bytes.saturating_add(bytes.len());
                item_memory = item_memory.saturating_add(bytes.capacity());
                ProjectionItem::Interval(bytes)
            };
            if result.retained_bytes > max_retained_bytes || item_memory > max_retained_bytes {
                return Ok(None);
            }
            result.pending().push(item);
            result.selected_events += 1;
            let memory = item_memory
                .saturating_add(result.pending().capacity() * 64)
                .saturating_add(seen.capacity() * 64)
                .saturating_add(generations.len() * 256)
                .saturating_add(path_memory)
                .saturating_add(max_page_bytes.saturating_mul(72));
            if memory > max_retained_bytes {
                return Ok(None);
            }
        }
        py.check_signals()?;
    }
    Ok(Some(result))
}

#[pyfunction(signature = (paths, query_json, max_page_bytes, max_event_bytes, max_page_events, max_depth=64, max_retained_bytes=536870912, max_selected_events=500000))]
fn project_quality_source(
    py: Python<'_>,
    paths: Vec<String>,
    query_json: &[u8],
    max_page_bytes: usize,
    max_event_bytes: usize,
    max_page_events: usize,
    max_depth: usize,
    max_retained_bytes: usize,
    max_selected_events: usize,
) -> PyResult<Option<VerifiedQualitySource>> {
    let Some(errors) = ProjectionErrorScope::start() else {
        return Ok(None);
    };
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        project_quality_source_impl(
            py,
            paths,
            query_json,
            max_page_bytes,
            max_event_bytes,
            max_page_events,
            max_depth,
            max_retained_bytes,
            max_selected_events,
        )
    }))
    .unwrap_or(Ok(None));
    if let Some(error) = errors.take() {
        return Err(error);
    }
    result
}

#[pymodule(gil_used = true)]
fn _archive_probe(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(read_original, module)?)?;
    module.add_function(wrap_pyfunction!(project_quality_source, module)?)?;
    module.add_class::<VerifiedConfiguration>()?;
    module.add_class::<VerifiedQualitySource>()?;
    module.add_class::<VerifiedQualityItems>()?;
    module.add("PROTOCOL_VERSION", 1)?;
    module.add("QUALITY_PROJECTION_VERSION", 2)?;
    module.add("MAX_FAST_DEPTH", 64)?;
    Ok(())
}
