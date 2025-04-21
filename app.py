import re
import pandas as pd
from PyPDF2 import PdfReader
import streamlit as st
from io import BytesIO

# === TOOL FUNCTION ===
def match_crds_from_pdf_and_excel(pdf_bytes, excel_bytes):
    pdf = PdfReader(BytesIO(pdf_bytes))
    pdf_text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])

    pdf_entries = re.findall(r"([A-Z][a-zA-Z .,'-]+?)\s*\(CRD #(\d+?)\).*?(Date:.*?)\n.*?(Action:.*?)\n.*?(Key Findings:.*?)\n.*?(FINRA Case #[0-9]+)", pdf_text, re.DOTALL)
    pdf_df = pd.DataFrame(pdf_entries, columns=["Name", "CRD", "Date", "Action", "Key Findings", "Case Number"])
    pdf_df["Source"] = "PDF"

    df = pd.read_excel(BytesIO(excel_bytes))

    required_columns = ["Individual Listed", "Business Name", "Summary of Disciplinary Action"]
    for col in required_columns:
        if col not in df.columns:
            return pd.DataFrame([{"Error": f"Missing required column in Excel: {col}"}])

    excel_data = []
    for _, row in df.iterrows():
        name_field = row.get("Individual Listed") or row.get("Business Name")
        if pd.isna(name_field):
            continue
        match = re.search(r"([A-Z][a-zA-Z .,'-]+?)\s*\(CRD #(\d+)\)", str(name_field))
        if match:
            summary = row.get("Summary of Disciplinary Action", "").split("\n")
            excel_data.append({
                "Name": match.group(1).strip(),
                "CRD": match.group(2).strip(),
                "City/State": row.get("City/State of Business or Individual", ""),
                "Fines/Restitution": row.get("Fines/Restitution", ""),
                "Date": summary[0].replace("Date: ", "") if len(summary) > 0 else "",
                "Action": summary[1].replace("Action: ", "") if len(summary) > 1 else "",
                "Key Findings": summary[2].replace("Key Findings: ", "") if len(summary) > 2 else "",
                "Case Number": re.search(r"FINRA Case #[0-9]+", row.get("Summary of Disciplinary Action", "")).group(0) if re.search(r"FINRA Case #[0-9]+", row.get("Summary of Disciplinary Action", "")) else ""
            })

    excel_df = pd.DataFrame(excel_data)
    excel_df["Source"] = "Excel"

    if "CRD" not in pdf_df.columns or "CRD" not in excel_df.columns:
        return pd.DataFrame([{"Error": "Missing CRD column in one of the sources. Ensure your Excel matches the required format."}])

    if pdf_df.empty or excel_df.empty:
        return pd.DataFrame([{"Error": "One or both sources did not contain extractable CRD data. Check file formatting."}])

    combined = pd.merge(pdf_df, excel_df, on="CRD", how="outer", suffixes=("_PDF", "_Excel"))

    for field in ["Name", "Date", "Action", "Key Findings", "Case Number", "Fines/Restitution", "City/State"]:
        combined[f"{field} Match"] = combined.apply(
            lambda row: "✅" if row.get(f"{field}_PDF") == row.get(f"{field}_Excel") else "❌", axis=1
        )

    combined["Status"] = combined.apply(
        lambda row: (
            "Missing in Excel" if pd.isna(row.get("Name_Excel")) else
            "Missing in PDF" if pd.isna(row.get("Name_PDF")) else
            "Mismatch" if any(row.get(f"{f} Match") == "❌" for f in [
                "Name", "Date", "Action", "Key Findings", "Case Number", "Fines/Restitution", "City/State"
            ]) else "Match"
        ),
        axis=1
    )

    return combined[combined["Status"] != "Match"].reset_index(drop=True)

# === STREAMLIT APP ===
st.set_page_config(page_title="CRD Checker Tool", layout="wide")
st.title("📄 FINRA Disciplinary Action Validator")

st.markdown("""
Upload a FINRA disciplinary PDF and the corresponding Excel workbook.
The tool will match entries by CRD and compare:
- ✅ Name
- ✅ Date
- ✅ Action
- ✅ Key Findings
- ✅ Case Number
- ✅ Fines/Restitution
- ✅ City/State

It will return a list of mismatches or missing entries.
""")

with st.sidebar:
    use_demo = st.checkbox("Use Demo Files")

if use_demo:
    pdf_file = open("demo_files/sample.pdf", "rb")
    excel_file = open("demo_files/sample.xlsx", "rb")
    st.success("Demo files loaded.")
else:
    pdf_file = st.file_uploader("Upload PDF Report", type=["pdf"])
    excel_file = st.file_uploader("Upload Excel File", type=["xlsx"])

if pdf_file and excel_file:
    with st.spinner("Analyzing files and matching CRD data..."):
        mismatches = match_crds_from_pdf_and_excel(pdf_file.read(), excel_file.read())

    if "Error" in mismatches.columns:
        st.error(mismatches.iloc[0]["Error"])
    else:
        st.success("Comparison complete! See results below.")

        search = st.text_input("Search by CRD")
        if search:
            mismatches = mismatches[mismatches["CRD"].astype(str).str.contains(search.strip())]

        st.dataframe(mismatches, use_container_width=True)

        csv = mismatches.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download Mismatches as CSV", data=csv, file_name="crd_mismatches.csv")
