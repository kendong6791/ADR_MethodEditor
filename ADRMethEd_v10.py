
import hashlib
import json
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd
import streamlit as st


APP_NAME = "Method Parameter Editor"
APP_VERSION = "0.10.0"


# -----------------------------
# General helpers
# -----------------------------

def get_nested_value(data, path):
    current = data
    for key in path:
        current = current[key]
    return current


def set_nested_value(data, path, value):
    current = data
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


def path_to_label(path):
    return ".".join(path)


def values_different(a, b):
    return a != b


def keep_original_numeric_type_when_unchanged(original_value, current_value, new_value):
    """
    Streamlit number_input can convert JSON integers to floats when a field is
    rendered as a general numeric field. If the numeric value has not changed,
    keep the currently stored JSON value exactly as it was so the downloaded
    file does not get harmless but noisy 4 -> 4.0 edits.
    """
    if isinstance(original_value, bool) or isinstance(current_value, bool):
        return new_value

    numeric_types = (int, float)
    if isinstance(original_value, numeric_types) and isinstance(new_value, numeric_types):
        if float(original_value) == float(new_value):
            return original_value

    if isinstance(current_value, numeric_types) and isinstance(new_value, numeric_types):
        if float(current_value) == float(new_value):
            return current_value

    return new_value


def decimal_places_from_decimal(value):
    """Return decimal-place precision encoded in a JSON float literal.

    json.loads(..., parse_float=Decimal) preserves literals such as 0.995,
    100.0, and 1e-6 as Decimals. The exponent tells us the number of places
    the input file implied for normal numeric editing.
    """
    if not isinstance(value, Decimal):
        return None
    return max(0, -value.as_tuple().exponent)


def convert_decimals_and_collect_precision(value, path=(), precision_map=None):
    """Convert Decimal values to ordinary JSON-compatible floats while storing
    the original numeric precision by absolute JSON path.
    """
    if precision_map is None:
        precision_map = {}

    if isinstance(value, Decimal):
        precision_map[path] = decimal_places_from_decimal(value)
        return float(value)

    if isinstance(value, list):
        return [
            convert_decimals_and_collect_precision(item, path + (idx,), precision_map)
            for idx, item in enumerate(value)
        ]

    if isinstance(value, dict):
        return {
            key: convert_decimals_and_collect_precision(item, path + (key,), precision_map)
            for key, item in value.items()
        }

    return value


def get_allowed_decimal_places(precision_map, analyte, component, path):
    full_path = tuple(["analyte_istd_map", analyte, component] + list(path))
    return precision_map.get(full_path)


def quantize_float_to_decimal_places(value, decimal_places):
    """Round a changed float to the precision implied by the input JSON."""
    if decimal_places is None:
        return value
    quantum = Decimal("1").scaleb(-decimal_places)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return float(rounded)


def number_widget_kwargs_for_precision(decimal_places):
    """Provide Streamlit number_input kwargs matching input-file precision."""
    if decimal_places is None:
        return {}
    step = float(Decimal("1").scaleb(-decimal_places)) if decimal_places > 0 else 1.0
    return {"step": step, "format": f"%.{decimal_places}f"}


def build_method_structure_summary(data):
    rows = []
    analyte_map = data.get("analyte_istd_map", {})

    for analyte_key, pair in analyte_map.items():
        for component in ["analyte", "internal_standard"]:
            method_data = pair.get(component)
            if not isinstance(method_data, dict):
                rows.append({
                    "Analyte key": analyte_key,
                    "Component": component,
                    "Embedded compound": "MISSING",
                    "Function index": None,
                    "Expected RT": None,
                    "Quan transition": None,
                    "Qualifier transitions": None,
                    "Status": "Missing component block",
                })
                continue

            quan = method_data.get("quan_transition", {}) or {}
            quals = method_data.get("qual_transitions", []) or []
            qual_names = [q.get("name") for q in quals if isinstance(q, dict)]
            embedded_name = method_data.get("compound_name")

            status_items = []
            if component == "analyte" and embedded_name != analyte_key:
                status_items.append("Analyte key differs from embedded compound")
            if component == "internal_standard" and not embedded_name:
                status_items.append("Missing embedded IS compound")
            if not quan.get("name"):
                status_items.append("Missing quantifier transition")

            rows.append({
                "Analyte key": analyte_key,
                "Component": component,
                "Embedded compound": embedded_name,
                "Function index": method_data.get("function_index"),
                "Expected RT": method_data.get("rt_params", {}).get("expected_rt"),
                "Quan transition": quan.get("name"),
                "Qualifier transitions": ", ".join(qual_names),
                "Status": "; ".join(status_items) if status_items else "OK",
            })

    return pd.DataFrame(rows)


def make_widget_key(file_signature, analyte, component, path, suffix="value"):
    """
    Build stable, collision-resistant widget keys. Paths may contain transition
    names such as "166.2 > 134.1", so hash the full identity rather than
    relying on simple string replacement.
    """
    identity = json.dumps(
        {
            "file": file_signature,
            "generation": st.session_state.get("widget_generation", 0),
            "analyte": analyte,
            "component": component,
            "path": path,
            "suffix": suffix,
        },
        sort_keys=True,
    )
    return "w_" + hashlib.md5(identity.encode("utf-8")).hexdigest()


def get_file_signature(file_bytes):
    return hashlib.md5(file_bytes).hexdigest()[:12]


def default_output_filename(input_filename):
    """Return a safe default output name using the uploaded filename stem."""
    path = Path(input_filename)
    suffix = path.suffix or ".json"
    return f"{path.stem}_edited{suffix}"


def normalise_output_filename(filename):
    """Ensure the download filename is non-empty and has a .json suffix."""
    cleaned = filename.strip()
    if not cleaned:
        cleaned = "edited_method.json"
    if not cleaned.lower().endswith(".json"):
        cleaned = f"{cleaned}.json"
    return cleaned


def parse_uploaded_json(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    file_signature = get_file_signature(file_bytes)
    raw_text = file_bytes.decode("utf-8")

    precision_map = {}
    decimal_data = json.loads(raw_text, parse_float=Decimal)
    data = convert_decimals_and_collect_precision(decimal_data, precision_map=precision_map)

    return data, file_signature, precision_map


def initialise_state_for_file(uploaded_file, original_data, file_signature, precision_map):
    current_file_key = f"{uploaded_file.name}:{file_signature}"

    if st.session_state.get("current_file_key") != current_file_key:
        st.session_state.current_file_key = current_file_key
        st.session_state.original_data = deepcopy(original_data)
        st.session_state.edited_data = deepcopy(original_data)
        st.session_state.precision_map = dict(precision_map)
        st.session_state.uploaded_filename = uploaded_file.name
        st.session_state.output_filename = default_output_filename(uploaded_file.name)
        st.session_state.widget_generation = 0

        # Remove any field widget state carried over from a previous uploaded file.
        for key in list(st.session_state.keys()):
            if isinstance(key, str) and key.startswith("w_"):
                del st.session_state[key]


def reset_edits():
    """Restore edited JSON and force fresh field widgets.

    Streamlit widget values are sticky: if a number_input has the same key after
    a reset, Streamlit can reuse the old value and immediately write it back
    into edited_data. To make reset reliable, this function does two things:

    1. Restores edited_data from original_data.
    2. Increments widget_generation, which is included in every editable field
       widget key. After st.rerun(), all field widgets are recreated with new
       keys and therefore initialise from the restored edited_data.

    The deletion loop is kept to clean up old generated field keys and avoid
    accumulating stale widget values in the session.
    """
    if "original_data" in st.session_state:
        st.session_state.edited_data = deepcopy(st.session_state.original_data)

    st.session_state.widget_generation = st.session_state.get("widget_generation", 0) + 1

    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith("w_"):
            del st.session_state[key]


# -----------------------------
# Field catalogue
# -----------------------------

BASE_FIELD_GROUPS = {
    "RT": [
        {"label": "Expected RT", "path": ["rt_params", "expected_rt"], "type": "number"},
        {"label": "Location tolerance lower", "path": ["rt_params", "location_tolerance", "lower"], "type": "number"},
        {"label": "Location tolerance upper", "path": ["rt_params", "location_tolerance", "upper"], "type": "number"},
        {"label": "Consistency tolerance lower", "path": ["rt_params", "consistency_tolerance", "lower"], "type": "number"},
        {"label": "Consistency tolerance upper", "path": ["rt_params", "consistency_tolerance", "upper"], "type": "number"},
    ],
    "Area / Ratio": [
        {"label": "Area consistency lower", "path": ["area_params", "consistency_tolerance_fraction", "lower"], "type": "number"},
        {"label": "Area consistency upper", "path": ["area_params", "consistency_tolerance_fraction", "upper"], "type": "number"},
        {"label": "Ion-ratio tolerance lower", "path": ["area_params", "ion_ratio_tolerance_fraction", "lower"], "type": "number"},
        {"label": "Ion-ratio tolerance upper", "path": ["area_params", "ion_ratio_tolerance_fraction", "upper"], "type": "number"},
    ],
    "Calibration": [
        {"label": "LLOQ", "path": ["calibration", "lloq"], "type": "nullable_number"},
        {"label": "ULOQ", "path": ["calibration", "uloq"], "type": "nullable_number"},
        {"label": "Fit type", "path": ["calibration", "fit_params", "fit_type"], "type": "select", "options": ["linear", "quadratic"]},
        {"label": "Weight function", "path": ["calibration", "fit_params", "weight_function"], "type": "select", "options": ["none", "oneoverx", "oneoverxsquared"]},
        {"label": "R² threshold", "path": ["calibration", "acceptance_params", "r2_threshold"], "type": "number"},
    ],
    "Peak Detection": [
        {"label": "Smooth iterations", "path": ["peak_detection", "proclibs", "smoothing", "smooth_iterations"], "type": "integer"},
        {"label": "Smooth width", "path": ["peak_detection", "proclibs", "smoothing", "smooth_width"], "type": "integer"},
        {"label": "Baseline start threshold (%)", "path": ["peak_detection", "proclibs", "apextrack", "baseline_start_threshold_pc"], "type": "number"},
        {"label": "Baseline end threshold (%)", "path": ["peak_detection", "proclibs", "apextrack", "baseline_end_threshold_pc"], "type": "number"},
        {"label": "Min S/N lower", "path": ["peak_detection", "proclibs", "limits", "min_signal_to_noise", "lower"], "type": "number"},
        {"label": "Min S/N upper", "path": ["peak_detection", "proclibs", "limits", "min_signal_to_noise", "upper"], "type": "number"},
        {"label": "Shape limit lower", "path": ["peak_detection", "proclibs", "limits", "shape_limits", "lower"], "type": "number"},
        {"label": "Shape limit upper", "path": ["peak_detection", "proclibs", "limits", "shape_limits", "upper"], "type": "number"},
    ],
    "Discovery": [
        {"label": "Error-bar sigma", "path": ["peak_detection", "discovery", "chromatogram", "error_bar", "proportion_sigma"], "type": "number"},
        {"label": "Baseline knots / HWHM", "path": ["peak_detection", "discovery", "chromatogram", "baseline", "num_knots_per_hwhm"], "type": "number"},
        {"label": "Baseline fraction below", "path": ["peak_detection", "discovery", "chromatogram", "baseline", "frac_below"], "type": "number"},
        {"label": "Baseline transform", "path": ["peak_detection", "discovery", "chromatogram", "baseline", "transform"], "type": "select", "options": ["none", "sqrt", "log"]},
        {"label": "Model width fraction", "path": ["peak_detection", "discovery", "model", "width_fraction"], "type": "number"},
        {"label": "Coeffs / basis HWHM", "path": ["peak_detection", "discovery", "model", "coeffs_per_basis_hwhm"], "type": "number"},
        {"label": "Model half window", "path": ["peak_detection", "discovery", "model", "half_window"], "type": "number"},
        {"label": "Max peaks", "path": ["peak_detection", "discovery", "deconv", "max_peaks"], "type": "integer"},
        {"label": "Deconv half window", "path": ["peak_detection", "discovery", "deconv", "half_window"], "type": "number"},
        {"label": "Dampening", "path": ["peak_detection", "discovery", "deconv", "dampening"], "type": "number"},
        {"label": "Separation", "path": ["peak_detection", "discovery", "deconv", "separation"], "type": "number"},
        {"label": "Max overlap lower", "path": ["peak_detection", "discovery", "limits", "max_overlap_percent", "lower"], "type": "number"},
        {"label": "Max overlap upper", "path": ["peak_detection", "discovery", "limits", "max_overlap_percent", "upper"], "type": "number"},
        {"label": "Max CV lower", "path": ["peak_detection", "discovery", "limits", "max_coeff_of_var_percent", "lower"], "type": "number"},
        {"label": "Max CV upper", "path": ["peak_detection", "discovery", "limits", "max_coeff_of_var_percent", "upper"], "type": "number"},
        {"label": "Knot multiplier", "path": ["peak_detection", "summation", "knot_multiplier"], "type": "number"},
    ],
}

ADVANCED_FIELD_GROUPS = {
    "Outliers": [
        {"label": "Half width", "path": ["outlier_params", "half_width"], "type": "integer"},
        {"label": "Order", "path": ["outlier_params", "order"], "type": "integer"},
        {"label": "Outlier sigma", "path": ["outlier_params", "outlier_sigma"], "type": "number"},
        {"label": "Prior sigma", "path": ["outlier_params", "prior_sigma"], "type": "number"},
        {"label": "Probability outlier", "path": ["outlier_params", "prob_outlier"], "type": "number"},
        {"label": "Noise-scale prior power", "path": ["outlier_params", "noise_scale_prior_power"], "type": "integer"},
    ],
    "Background": [
        {"label": "RT range start", "path": ["background_params", "rt_range", "start"], "type": "float_text"},
        {"label": "RT range end", "path": ["background_params", "rt_range", "end"], "type": "float_text"},
        {"label": "Mean limit lower", "path": ["background_params", "mean_limits", "lower"], "type": "float_text"},
        {"label": "Mean limit upper", "path": ["background_params", "mean_limits", "upper"], "type": "float_text"},
    ],
    "Concentration": [
        {"label": "Qualifier absence level fraction", "path": ["concentration_params", "qualifier_absence_level_fraction"], "type": "number"},
        {"label": "Blank limit lower", "path": ["concentration_params", "blank_limit_fraction", "lower"], "type": "number"},
        {"label": "Blank limit upper", "path": ["concentration_params", "blank_limit_fraction", "upper"], "type": "number"},
    ],
    "Calibration Advanced": [
        {"label": "Shape tolerance lower", "path": ["calibration", "shape_params", "shape_tolerance", "lower"], "type": "float_text"},
        {"label": "Shape tolerance upper", "path": ["calibration", "shape_params", "shape_tolerance", "upper"], "type": "float_text"},
        {"label": "Ion-ratio tolerance lower", "path": ["calibration", "ion_ratio_params", "ion_ratio_tolerance_fraction", "lower"], "type": "float_text"},
        {"label": "Ion-ratio tolerance upper", "path": ["calibration", "ion_ratio_params", "ion_ratio_tolerance_fraction", "upper"], "type": "float_text"},
    ],
    "Deconv Advanced": [
        {"label": "Sampling ensemble", "path": ["peak_detection", "discovery", "deconv", "sampling_params", "ensemble"], "type": "integer"},
        {"label": "Sampling MCMC", "path": ["peak_detection", "discovery", "deconv", "sampling_params", "mcmc"], "type": "integer"},
        {"label": "Sampling simulations", "path": ["peak_detection", "discovery", "deconv", "sampling_params", "simulations"], "type": "integer"},
        {"label": "Sampling seed", "path": ["peak_detection", "discovery", "deconv", "sampling_params", "seed"], "type": "integer"},
        {"label": "Max samples", "path": ["peak_detection", "discovery", "deconv", "sampling_params", "max_samples"], "type": "integer"},
        {"label": "Minimum iterations", "path": ["peak_detection", "discovery", "deconv", "termination_params", "min_iterations"], "type": "integer"},
        {"label": "h delta", "path": ["peak_detection", "discovery", "deconv", "termination_params", "h_delta"], "type": "number"},
        {"label": "log Z delta", "path": ["peak_detection", "discovery", "deconv", "termination_params", "log_z_delta"], "type": "number"},
    ],
}


def get_transition_efficiency_fields(method_data):
    """Return one editable field per transition-efficiency key for this compound."""
    efficiencies = (
        method_data
        .get("calibration", {})
        .get("ion_ratio_params", {})
        .get("transition_efficiencies", {})
    )
    fields = []
    if isinstance(efficiencies, dict):
        for transition_name in efficiencies.keys():
            fields.append({
                "label": f"Transition efficiency: {transition_name}",
                "path": ["calibration", "ion_ratio_params", "transition_efficiencies", transition_name],
                "type": "number",
            })
    return fields


def get_field_groups(method_data=None, include_advanced=True):
    groups = {name: list(fields) for name, fields in BASE_FIELD_GROUPS.items()}
    if include_advanced:
        for name, fields in ADVANCED_FIELD_GROUPS.items():
            groups[name] = list(fields)
        if method_data is not None:
            transition_fields = get_transition_efficiency_fields(method_data)
            if transition_fields:
                groups["Calibration Advanced"] = groups["Calibration Advanced"] + transition_fields
    return groups


# Backward-compatible alias used by older helper logic, if needed.
FIELD_GROUPS = get_field_groups(include_advanced=True)


# -----------------------------
# Rendering helpers
# -----------------------------

def render_number_field(label, original_method_data, edited_method_data, path, file_signature, analyte, component, precision_map, integer=False):
    original_value = get_nested_value(original_method_data, path)
    current_value = get_nested_value(edited_method_data, path)
    key = make_widget_key(file_signature, analyte, component, path)

    if integer:
        new_value = st.number_input(label, value=int(current_value), step=1, key=key)
        new_value = int(new_value)
    else:
        decimal_places = get_allowed_decimal_places(precision_map, analyte, component, path)
        precision_kwargs = number_widget_kwargs_for_precision(decimal_places)
        raw_new_value = st.number_input(label, value=float(current_value), key=key, **precision_kwargs)

        if float(original_value) == float(raw_new_value):
            new_value = original_value
        elif float(current_value) == float(raw_new_value):
            new_value = current_value
        else:
            new_value = quantize_float_to_decimal_places(raw_new_value, decimal_places)

    set_nested_value(edited_method_data, path, new_value)

    return {
        "Analyte": analyte,
        "Component": component,
        "Parameter": label,
        "Path": path_to_label(path),
        "Original Value": original_value,
        "New Value": new_value,
        "Changed": values_different(original_value, new_value),
    }


def render_nullable_number_field(label, original_method_data, edited_method_data, path, file_signature, analyte, component, precision_map):
    original_value = get_nested_value(original_method_data, path)
    current_value = get_nested_value(edited_method_data, path)

    enabled_key = make_widget_key(file_signature, analyte, component, path, suffix="enabled")
    value_key = make_widget_key(file_signature, analyte, component, path, suffix="value")

    enabled = st.checkbox(
        f"Set {label}",
        value=current_value is not None,
        key=enabled_key,
    )

    if enabled:
        decimal_places = get_allowed_decimal_places(precision_map, analyte, component, path)
        precision_kwargs = number_widget_kwargs_for_precision(decimal_places)
        default_value = 0.0 if current_value is None else float(current_value)
        raw_new_value = st.number_input(label, value=default_value, key=value_key, **precision_kwargs)
        if current_value is not None and original_value is not None and float(original_value) == float(raw_new_value):
            new_value = original_value
        elif current_value is not None and float(current_value) == float(raw_new_value):
            new_value = current_value
        else:
            new_value = quantize_float_to_decimal_places(raw_new_value, decimal_places)
    else:
        new_value = None

    set_nested_value(edited_method_data, path, new_value)

    return {
        "Analyte": analyte,
        "Component": component,
        "Parameter": label,
        "Path": path_to_label(path),
        "Original Value": original_value,
        "New Value": new_value,
        "Changed": values_different(original_value, new_value),
    }



def render_float_text_field(label, original_method_data, edited_method_data, path, file_signature, analyte, component):
    """
    Render numerics as text where very large sentinel values such as
    1.7976931348623157e308 are expected. This avoids browser/number-widget
    quirks while still validating that the submitted value is numeric.
    """
    original_value = get_nested_value(original_method_data, path)
    current_value = get_nested_value(edited_method_data, path)
    key = make_widget_key(file_signature, analyte, component, path)

    raw_value = st.text_input(label, value=str(current_value), key=key)
    try:
        parsed_value = float(raw_value)
        new_value = keep_original_numeric_type_when_unchanged(original_value, current_value, parsed_value)
        set_nested_value(edited_method_data, path, new_value)
    except ValueError:
        st.error(f"{label} must be a numeric value.")
        new_value = current_value

    return {
        "Analyte": analyte,
        "Component": component,
        "Parameter": label,
        "Path": path_to_label(path),
        "Original Value": original_value,
        "New Value": new_value,
        "Changed": values_different(original_value, new_value),
    }

def render_select_field(label, original_method_data, edited_method_data, path, options, file_signature, analyte, component):
    original_value = get_nested_value(original_method_data, path)
    current_value = get_nested_value(edited_method_data, path)
    key = make_widget_key(file_signature, analyte, component, path)

    display_options = list(options)
    if current_value not in display_options:
        display_options = [current_value] + display_options

    new_value = st.selectbox(
        label,
        options=display_options,
        index=display_options.index(current_value),
        key=key,
    )

    set_nested_value(edited_method_data, path, new_value)

    return {
        "Analyte": analyte,
        "Component": component,
        "Parameter": label,
        "Path": path_to_label(path),
        "Original Value": original_value,
        "New Value": new_value,
        "Changed": values_different(original_value, new_value),
    }


def render_field_grid(fields, original_method_data, edited_method_data, file_signature, analyte, component, precision_map):
    changes = []

    for row_start in range(0, len(fields), 3):
        row_fields = fields[row_start:row_start + 3]
        cols = st.columns(3)

        for col, field in zip(cols, row_fields):
            with col:
                try:
                    if field["type"] == "number":
                        change = render_number_field(
                            field["label"], original_method_data, edited_method_data,
                            field["path"], file_signature, analyte, component, precision_map
                        )
                    elif field["type"] == "integer":
                        change = render_number_field(
                            field["label"], original_method_data, edited_method_data,
                            field["path"], file_signature, analyte, component, precision_map, integer=True
                        )
                    elif field["type"] == "nullable_number":
                        change = render_nullable_number_field(
                            field["label"], original_method_data, edited_method_data,
                            field["path"], file_signature, analyte, component, precision_map
                        )
                    elif field["type"] == "float_text":
                        change = render_float_text_field(
                            field["label"], original_method_data, edited_method_data,
                            field["path"], file_signature, analyte, component
                        )
                    elif field["type"] == "select":
                        change = render_select_field(
                            field["label"], original_method_data, edited_method_data,
                            field["path"], field["options"], file_signature, analyte, component
                        )
                    else:
                        raise ValueError(f"Unsupported field type: {field['type']}")
                    changes.append(change)
                except KeyError:
                    st.warning(f"Missing parameter: {field['label']}")

    return changes


def build_change_summary(original_data, edited_data):
    rows = []

    for analyte_name, pair in original_data["analyte_istd_map"].items():
        for component in ["analyte", "internal_standard"]:
            if component not in pair:
                continue

            original_method_data = original_data["analyte_istd_map"][analyte_name][component]
            edited_method_data = edited_data["analyte_istd_map"][analyte_name][component]

            field_groups = get_field_groups(edited_method_data, include_advanced=True)

            for group_name, fields in field_groups.items():
                for field in fields:
                    path = field["path"]

                    try:
                        original_value = get_nested_value(original_method_data, path)
                        new_value = get_nested_value(edited_method_data, path)
                    except KeyError:
                        continue

                    if values_different(original_value, new_value):
                        rows.append(
                            {
                                "Analyte key": analyte_name,
                                "Embedded compound": edited_method_data.get("compound_name"),
                                "Component": component,
                                "Group": group_name,
                                "Parameter": field["label"],
                                "Path": path_to_label(path),
                                "Original Value": original_value,
                                "New Value": new_value,
                            }
                        )

    return pd.DataFrame(rows)


def render_summary(method_data):
    st.subheader("Compound identity")
    st.write("These fields are shown read-only in this version.")

    st.json(
        {
            "compound_name": method_data.get("compound_name"),
            "function_index": method_data.get("function_index"),
            "quan_transition": method_data.get("quan_transition"),
            "qual_transitions": method_data.get("qual_transitions"),
        }
    )


# -----------------------------
# Main app
# -----------------------------

def main():
    st.set_page_config(page_title=APP_NAME, layout="wide")

    st.title(APP_NAME)
    st.caption(f"Version {APP_VERSION}")

    uploaded_file = st.file_uploader(
        "Select a processing method JSON file",
        type=["json"],
    )

    if uploaded_file is None:
        st.info("Upload a JSON method file to begin.")
        return

    try:
        original_data, file_signature, precision_map = parse_uploaded_json(uploaded_file)
    except json.JSONDecodeError as exc:
        st.error(f"Invalid JSON file: {exc}")
        return
    except UnicodeDecodeError as exc:
        st.error(f"Could not read file as UTF-8 JSON: {exc}")
        return

    if "analyte_istd_map" not in original_data:
        st.error("This JSON does not contain an 'analyte_istd_map' object.")
        return

    initialise_state_for_file(uploaded_file, original_data, file_signature, precision_map)

    original_data = st.session_state.original_data
    edited_data = st.session_state.edited_data
    precision_map = st.session_state.get("precision_map", {})

    analyte_names = list(edited_data["analyte_istd_map"].keys())

    selected_analyte = st.sidebar.selectbox("Analyte", analyte_names)
    selected_component = st.sidebar.radio("Component", ["analyte", "internal_standard"])
    show_advanced = st.sidebar.toggle("Advanced editing", value=False)

    original_method_data = original_data["analyte_istd_map"][selected_analyte][selected_component]
    edited_method_data = edited_data["analyte_istd_map"][selected_analyte][selected_component]

    st.sidebar.markdown("---")
    st.sidebar.write("Selected compound:")
    st.sidebar.code(edited_method_data.get("compound_name", "UNKNOWN"))

    st.sidebar.markdown("---")
    if st.sidebar.button("Reset all edits"):
        reset_edits()
        st.rerun()

    st.header(f"{selected_analyte} — {selected_component}")

    field_groups = get_field_groups(edited_method_data, include_advanced=show_advanced)

    tab_names = ["Summary", "Method Structure"] + list(field_groups.keys()) + ["JSON Preview"]
    tabs = st.tabs(tab_names)
    tab_lookup = dict(zip(tab_names, tabs))

    with tab_lookup["Summary"]:
        render_summary(edited_method_data)
        st.info(
            "Use the Advanced editing toggle in the sidebar to expose outlier, background, "
            "concentration, calibration-advanced, and deconvolution-advanced parameters."
        )

    with tab_lookup["Method Structure"]:
        st.subheader("Interpreted method structure")
        st.write(
            "This table shows how the app interprets each top-level analyte key and the "
            "embedded compound names inside the analyte and internal-standard blocks."
        )
        structure_summary = build_method_structure_summary(edited_data)
        st.dataframe(structure_summary, width="stretch", hide_index=True)

    for group_name, fields in field_groups.items():
        with tab_lookup[group_name]:
            st.subheader(f"{group_name} parameters")
            if group_name in ADVANCED_FIELD_GROUPS:
                st.caption("Advanced parameters: edit only when you are intentionally changing method-processing behaviour.")
            render_field_grid(
                fields,
                original_method_data,
                edited_method_data,
                file_signature,
                selected_analyte,
                selected_component,
                precision_map,
            )

    with tab_lookup["JSON Preview"]:
        st.subheader("Edited JSON preview")
        st.json(edited_data)

    st.markdown("---")
    st.header("Change summary")

    change_summary = build_change_summary(original_data, edited_data)

    if change_summary.empty:
        st.info("No changes have been made.")
    else:
        st.dataframe(change_summary, width="stretch", hide_index=True)

    st.markdown("---")
    st.header("Save edited method")

    st.warning(
        "Review the change summary before using the edited method file. "
        "This tool edits JSON values but does not validate analytical suitability."
    )

    default_name = st.session_state.get(
        "output_filename",
        default_output_filename(st.session_state.get("uploaded_filename", uploaded_file.name)),
    )

    requested_output_name = st.text_input(
        "Output filename",
        value=default_name,
        help="Edit the filename used for the downloaded JSON. The app will add .json if omitted.",
        key="output_filename",
        width="stretch",
    )
    output_name = normalise_output_filename(requested_output_name)

    try:
        output_json = json.dumps(edited_data, indent=2, allow_nan=False)
    except ValueError as exc:
        st.error(f"Edited JSON could not be serialized: {exc}")
        return

    st.download_button(
        label="Download edited JSON",
        data=output_json,
        file_name=output_name,
        mime="application/json",
        width="stretch",
    )


if __name__ == "__main__":
    main()
