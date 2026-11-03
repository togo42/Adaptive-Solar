//! Optional CPython host experiment. Every uncertainty returns None; Python
//! remains the authoritative reader and error producer. No archive writes.
use flate2::read::MultiGzDecoder;
use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::ffi::{c_char, c_double, c_int, CStr, CString};
use std::fs::{self, File};
use std::io::Read;
use std::path::Path;

const HARD_PAGE_BYTES: usize = 4 * 1024 * 1024;
const HARD_EVENT_BYTES: usize = 1024 * 1024;
const MAX_INTEGER: i64 = i64::MAX;
const ADD_DOT_ZERO: c_int = 0x02;

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
    unsafe { ffi::PyErr_Clear() }
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

fn utc_stamp(value: &Value) -> Option<()> {
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
    (year > 0
        && day > 0
        && day <= days
        && digits(11, 13)? < 24
        && digits(14, 16)? < 60
        && digits(17, 19)? < 60)
        .then_some(())
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

fn validate(value: &Value, max_page: usize, max_event: usize, max_events: usize) -> Option<()> {
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
        encoder.encode(event, max_event, false)?;
        if event_gen != gen || sequence != previous.checked_add(1)? {
            return None;
        }
        previous = sequence;
    }
    (next_seq == previous && next_seq <= MAX_INTEGER).then_some(())
}

fn read_impl(
    path: &Path,
    max_page: usize,
    max_event: usize,
    max_events: usize,
    max_depth: usize,
) -> Option<Vec<u8>> {
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
    validate(&value, max_page, max_event, max_events)?;
    Some(raw)
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

#[pymodule(gil_used = true)]
fn _archive_probe(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(read_original, module)?)?;
    module.add("PROTOCOL_VERSION", 1)?;
    module.add("MAX_FAST_DEPTH", 64)?;
    Ok(())
}
