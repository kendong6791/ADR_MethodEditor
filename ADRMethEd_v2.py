
import json
from copy import deepcopy
from pathlib import Path

import pandas as pd
import streamlit as st


APP_NAME = "Method Parameter Editor"
APP_VERSION = "0.2.0"


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


def render_number_field(label, original_method_data, edited_method_data, path):
    key = f"{label}_{path_to_label(path)}"

    original_value = get_nested_value(original_method_data, path)

    if original_value is None:
        enabled = st.checkbox(
            f"Set {label}",
            value=False,
            key=f"enable_{key}",
        )

        if enabled:
            new_value = st.number_input(
                label,
                value=0.0,
                key=f"value_{key}",
            )
        else:
            new_value = None

    elif isinstance(original_value, int) and not isinstance(original_value, bool):
        new_value = st.number_input(
            label,
            value=int(original_value),
            step=1,
            key=f"value_{key}",
        )

    else:
        new_value = st.number_input(
            label,
            value=float(original_value),
            key=f"value_{key}",
        )

    set_nested_value(edited_method_data, path, new_value)

    return {
        "Parameter": label,
        "Path": path_to_label(path),
        "Original Value": original_value,
        "New Value": new_value,
        "Changed": values_different(original_value, new_value),
    }


def render_select_field(label, original_method_data, edited_method_data, path, options):
    key = f"{label}_{path_to_label(path)}"

    original_value = get_nested_value(original_method_data, path)

    if original_value in options:
        index = options.index(original_value)
    else:
        options = [original_value] + options
        index = 0

    new_value = st.selectbox(
        label,
        options=options,
        index=index,
        key=f"value_{key}",
    )

    set_nested_value(edited_method_data, path, new_value)

    return {
        "Parameter": label,
        "Path": path_to_label(path),
        "Original Value": original_value,
        "New Value": new_value,
        "Changed": values_different(original_value, new_value),
    }


def render_field_grid(fields, original_method_data, edited_method_data):
    """
    Renders editable fields 3 across.

    Each item in fields should be either:
    {
        "label": "...",
        "path": [...],
        "type": "number"
    }

    or:

    {
        "label": "...",
        "path": [...],
        "type": "select",
        "options": [...]
    }
    """

    changes = []

    for row_start in range(0, len(fields), 3):
        row_fields = fields[row_start:row_start + 3]
        cols = st.columns(3)

        for col, field in zip(cols, row_fields):
            with col:
                if field["type"] == "number":
                    change = render_number_field(
                        field["label"],
                        original_method_data,
                        edited_method_data,
                        field["path"],
                    )
                elif field["type"] == "select":
                    change = render_select_field(
                        field["label"],
                        original_method_data,
                        edited_method_data,
                        field["path"],
                        field["options"],
                    )
                else:
                    raise ValueError(f"Unsupported field type: {field['type']}")

                changes.append(change)

    return changes


def render_rt_editor(original_method_data, edited_method_data):
    st.subheader("Retention time parameters")

    fields = [
        {
            "label": "Expected RT",
            "path": ["rt_params", "expected_rt"],
            "type": "number",
        },
        {
            "label": "Location tolerance lower",
            "path": ["rt_params", "location_tolerance", "lower"],
            "type": "number",
        },
        {
            "label": "Location tolerance upper",
            "path": ["rt_params", "location_tolerance", "upper"],
            "type": "number",
        },
        {
            "label": "Consistency tolerance lower",
            "path": ["rt_params", "consistency_tolerance", "lower"],
            "type": "number",
        },
        {
            "label": "Consistency tolerance upper",
            "path": ["rt_params", "consistency_tolerance", "upper"],
            "type": "number",
        },
    ]

    return render_field_grid(fields, original_method_data, edited_method_data)


def render_area_editor(original_method_data, edited_method_data):
    st.subheader("Area and ion-ratio parameters")

    fields = [
        {
            "label": "Area consistency lower",
            "path": ["area_params", "consistency_tolerance_fraction", "lower"],
            "type": "number",
        },
        {
            "label": "Area consistency upper",
            "path": ["area_params", "consistency_tolerance_fraction", "upper"],
            "type": "number",
        },
        {
            "label": "Ion-ratio tolerance lower",
            "path": ["area_params", "ion_ratio_tolerance_fraction", "lower"],
            "type": "number",
        },
        {
            "label": "Ion-ratio tolerance upper",
            "path": ["area_params", "ion_ratio_tolerance_fraction", "upper"],
            "type": "number",
        },
    ]

    return render_field_grid(fields, original_method_data, edited_method_data)


def render_calibration_editor(original_method_data, edited_method_data):
    st.subheader("Calibration parameters")

    fields = [
        {
            "label": "LLOQ",
            "path": ["calibration", "lloq"],
            "type": "number",
        },
        {
            "label": "ULOQ",
            "path": ["calibration", "uloq"],
            "type": "number",
        },
        {
            "label": "Fit type",
            "path": ["calibration", "fit_params", "fit_type"],
            "type": "select",
            "options": ["linear", "quadratic"],
        },
        {
            "label": "Weight function",
            "path": ["calibration", "fit_params", "weight_function"],
            "type": "select",
            "options": ["none", "oneoverx", "oneoverxsquared"],
        },
        {
            "label": "R² threshold",
            "path": ["calibration", "acceptance_params", "r2_threshold"],
            "type": "number",
        },
    ]

    return render_field_grid(fields, original_method_data, edited_method_data)


def render_peak_detection_editor(original_method_data, edited_method_data):
    st.subheader("Peak detection parameters")

    fields = [
        {
            "label": "Smooth iterations",
            "path": ["peak_detection", "proclibs", "smoothing", "smooth_iterations"],
            "type": "number",
        },
        {
            "label": "Smooth width",
            "path": ["peak_detection", "proclibs", "smoothing", "smooth_width"],
            "type": "number",
        },
        {
            "label": "Baseline start threshold (%)",
            "path": ["peak_detection", "proclibs", "apextrack", "baseline_start_threshold_pc"],
            "type": "number",
        },
        {
            "label": "Baseline end threshold (%)",
            "path": ["peak_detection", "proclibs", "apextrack", "baseline_end_threshold_pc"],
            "type": "number",
        },
        {
            "label": "Min S/N lower",
            "path": ["peak_detection", "proclibs", "limits", "min_signal_to_noise", "lower"],
            "type": "number",
        },
        {
            "label": "Min S/N upper",
            "path": ["peak_detection", "proclibs", "limits", "min_signal_to_noise", "upper"],
            "type": "number",
        },
        {
            "label": "Shape limit lower",
            "path": ["peak_detection", "proclibs", "limits", "shape_limits", "lower"],
            "type": "number",
        },
        {
            "label": "Shape limit upper",
            "path": ["peak_detection", "proclibs", "limits", "shape_limits", "upper"],
            "type": "number",
        },
    ]

    return render_field_grid(fields, original_method_data, edited_method_data)


def render_discovery_editor(original_method_data, edited_method_data):
    st.subheader("Discovery / deconvolution parameters")

    fields = [
        {
            "label": "Error-bar sigma",
            "path": [
                "peak_detection",
                "discovery",
                "chromatogram",
                "error_bar",
                "proportion_sigma",
            ],
            "type": "number",
        },
        {
            "label": "Baseline knots / HWHM",
            "path": [
                "peak_detection",
                "discovery",
                "chromatogram",
                "baseline",
                "num_knots_per_hwhm",
            ],
            "type": "number",
        },
        {
            "label": "Baseline fraction below",
            "path": [
                "peak_detection",
                "discovery",
                "chromatogram",
                "baseline",
                "frac_below",
            ],
            "type": "number",
        },
        {
            "label": "Model width fraction",
            "path": ["peak_detection", "discovery", "model", "width_fraction"],
            "type": "number",
        },
        {
            "label": "Coeffs / basis HWHM",
            "path": ["peak_detection", "discovery", "model", "coeffs_per_basis_hwhm"],
            "type": "number",
        },
        {
            "label": "Model half window",
            "path": ["peak_detection", "discovery", "model", "half_window"],
            "type": "number",
        },
        {
            "label": "Max peaks",
            "path": ["peak_detection", "discovery", "deconv", "max_peaks"],
            "type": "number",
        },
        {
            "label": "Deconv half window",
            "path": ["peak_detection", "discovery", "deconv", "half_window"],
            "type": "number",
        },
        {
            "label": "Dampening",
            "path": ["peak_detection", "discovery", "deconv", "dampening"],
            "type": "number",
        },
        {
            "label": "Separation",
            "path": ["peak_detection", "discovery", "deconv", "separation"],
            "type": "number",
        },
        {
            "label": "Max overlap lower",
            "path": [
                "peak_detection",
                "discovery",
                "limits",
                "max_overlap_percent",
                "lower",
            ],
            "type": "number",
        },
        {
            "label": "Max overlap upper",
            "path": [
                "peak_detection",
                "discovery",
                "limits",
                "max_overlap_percent",
                "upper",
            ],
            "type": "number",
        },
        {
            "label": "Max CV lower",
            "path": [
                "peak_detection",
                "discovery",
                "limits",
                "max_coeff_of_var_percent",
                "lower",
            ],
            "type": "number",
        },
        {
            "label": "Max CV upper",
            "path": [
                "peak_detection",
                "discovery",
                "limits",
                "max_coeff_of_var_percent",
                "upper",
            ],
            "type": "number",
        },
        {
            "label": "Knot multiplier",
            "path": ["peak_detection", "summation", "knot_multiplier"],
            "type": "number",
        },
    ]

    return render_field_grid(fields, original_method_data, edited_method_data)


def build_change_summary(all_changes, selected_analyte, selected_component):
    rows = []

    for change in all_changes:
        if change["Changed"]:
            rows.append(
                {
                    "Analyte": selected_analyte,
                    "Component": selected_component,
                    "Parameter": change["Parameter"],
                    "Path": change["Path"],
                    "Original Value": change["Original Value"],
                    "New Value": change["New Value"],
                }
            )

    return pd.DataFrame(rows)


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
        original_data = json.load(uploaded_file)
    except json.JSONDecodeError as exc:
        st.error(f"Invalid JSON file: {exc}")
        return

    if "analyte_istd_map" not in original_data:
        st.error("This JSON does not contain an 'analyte_istd_map' object.")
        return

    edited_data = deepcopy(original_data)

    analyte_names = list(edited_data["analyte_istd_map"].keys())

    selected_analyte = st.sidebar.selectbox(
        "Analyte",
        analyte_names,
    )

    selected_component = st.sidebar.radio(
        "Component",
        ["analyte", "internal_standard"],
    )

    original_method_data = original_data["analyte_istd_map"][selected_analyte][selected_component]
    edited_method_data = edited_data["analyte_istd_map"][selected_analyte][selected_component]

    st.sidebar.markdown("---")
    st.sidebar.write("Selected compound:")
    st.sidebar.code(edited_method_data.get("compound_name", "UNKNOWN"))

    st.header(f"{selected_analyte} — {selected_component}")

    tab_summary, tab_rt, tab_area, tab_calibration, tab_peak, tab_discovery, tab_json = st.tabs(
        [
            "Summary",
            "RT",
            "Area / Ratio",
            "Calibration",
            "Peak Detection",
            "Discovery",
            "JSON Preview",
        ]
    )

    all_changes = []

    with tab_summary:
        st.subheader("Compound identity")
        st.write("These fields are shown read-only in this version.")

        st.json(
            {
                "compound_name": edited_method_data.get("compound_name"),
                "function_index": edited_method_data.get("function_index"),
                "quan_transition": edited_method_data.get("quan_transition"),
                "qual_transitions": edited_method_data.get("qual_transitions"),
            }
        )

    with tab_rt:
        all_changes.extend(
            render_rt_editor(original_method_data, edited_method_data)
        )

    with tab_area:
        all_changes.extend(
            render_area_editor(original_method_data, edited_method_data)
        )

    with tab_calibration:
        all_changes.extend(
            render_calibration_editor(original_method_data, edited_method_data)
        )

    with tab_peak:
        all_changes.extend(
            render_peak_detection_editor(original_method_data, edited_method_data)
        )

    with tab_discovery:
        all_changes.extend(
            render_discovery_editor(original_method_data, edited_method_data)
        )

    with tab_json:
        st.subheader("Edited JSON preview")
        st.json(edited_data)

    st.markdown("---")
    st.header("Change summary")

    change_summary = build_change_summary(
        all_changes,
        selected_analyte,
        selected_component,
    )

    if change_summary.empty:
        st.info("No changes have been made to the selected analyte/component.")
    else:
        st.dataframe(
            change_summary,
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("---")
    st.header("Save edited method")

    original_name = uploaded_file.name
    stem = Path(original_name).stem
    output_name = f"{stem}_edited.json"

    output_json = json.dumps(edited_data, indent=2, allow_nan=False)

    st.download_button(
        label="Download edited JSON",
        data=output_json,
        file_name=output_name,
        mime="application/json",
        use_container_width=False,
    )


if __name__ == "__main__":
    main()