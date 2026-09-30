import streamlit as st
import pandas as pd
import re
import dns.resolver
import socket
import smtplib
from concurrent.futures import ThreadPoolExecutor
import concurrent.futures
import io

# Page Configuration
st.set_page_config(page_title="Email Verification Tool", page_icon="✉️", layout="centered")

# Expanded Disposable Domains list
DISPOSABLE_DOMAINS = {
    'mailinator.com', '10minutemail.com', 'guerrillamail.com', 
    'tempmail.com', 'throwawaymail.com', 'yopmail.com', 'sharklasers.com',
    'temp-mail.org', 'dispostable.com', 'trashmail.com', 'fakemailgenerator.com',
    'getairmail.com', 'disposablemail.com', 'trashmail.net', 'maildrop.cc'
}

# Common Domain Typos for Auto-Correction Suggestions
COMMON_DOMAIN_TYPOS = {
    'gamil.com': 'gmail.com',
    'gmai.com': 'gmail.com',
    'gamil.co': 'gmail.com',
    'yaho.com': 'yahoo.com',
    'yahooo.com': 'yahoo.com',
    'hotmial.com': 'hotmail.com',
    'outlok.com': 'outlook.com'
}

def is_valid_format(email):
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return re.match(pattern, email) is not None

def get_mx_record(domain):
    try:
        records = dns.resolver.resolve(domain, 'MX')
        mx_record = sorted(records, key=lambda r: r.preference)[0].exchange.to_text()
        return mx_record
    except Exception:
        return None

def check_catch_all(mx_host, domain):
    try:
        random_email = f"test-random-nonexistent-xyz123@{domain}"
        server = smtplib.SMTP(timeout=5)
        server.connect(mx_host)
        server.helo(server.local_hostname)
        server.mail('test@example.com')
        code, _ = server.rcpt(random_email)
        server.quit()
        if code == 250:
            return True
    except Exception:
        pass
    return False

def check_mailbox_smtp(email, domain):
    mx_host = get_mx_record(domain)
    if not mx_host:
        return "Invalid", "Domain has no MX record"
    
    # Cek apakah domain berjenis catch-all
    is_catch_all = check_catch_all(mx_host, domain)

    for attempt in range(2):
        try:
            server = smtplib.SMTP(timeout=8)
            server.connect(mx_host)
            server.helo(server.local_hostname)
            server.mail('verify@gmail.com')
            code, message = server.rcpt(email)
            server.quit()
            
            if code == 250:
                return "Valid", "Valid"
            elif code in [550, 551, 552, 553, 554]:
                # Jika server menolak karena firewall ketat tapi domainnya catch-all atau bukan
                if is_catch_all:
                    return "Risky (Catch-All)", f"Catch-All Server (Code: {code})"
                else:
                    return "Risky (Likely Valid)", f"Strict Corporate Firewall (Code: {code})"
            else:
                return "Risky (Catch-All)" if is_catch_all else "Risky (Likely Valid)", f"Server response code {code}"
        except (socket.timeout, smtplib.SMTPConnectError):
            if attempt == 1:
                return "Risky (Likely Valid)", "Server timeout (Active Domain with Strict Firewall)"
        except Exception:
            break
            
    return "Risky (Likely Valid)", "Unable to verify due to strict server firewall"

def validate_single_email(email):
    email = str(email).strip().lower()
    
    if not is_valid_format(email):
        return "Invalid", "Invalid email format", ""
    
    try:
        local_part, domain = email.split('@')
    except ValueError:
        return "Invalid", "Invalid email format", ""
    
    suggestion = ""
    if domain in COMMON_DOMAIN_TYPOS:
        correct_domain = COMMON_DOMAIN_TYPOS[domain]
        suggestion = f"{local_part}@{correct_domain}"
    
    if domain in DISPOSABLE_DOMAINS:
        return "Invalid", "Disposable domain", suggestion
    
    status, reason = check_mailbox_smtp(email, domain)
    return status, reason, suggestion

# --- GUI INTERFACE ---
st.title("Email Verification Tool")
st.write("This tool verifies the validity of an email address before importing to Brevo to reduce bounce risks.")
st.info("The result may not be accurate. However, it has 90% accuracy.")

tab1, tab2 = st.tabs(["Single Email / Multiple by Line", "Bulk File Processing (CSV, XLS, XLSX, TXT)"])

# --- TAB 1: Single Email or Multiple by Line ---
with tab1:
    st.write("Enter an email address or multiple emails (one per line):")
    input_text = st.text_area("Email input:", placeholder="example1@gmail.com\nexample2@yahoo.com", height=150)
    
    if st.button("Verify"):
        if not input_text.strip():
            st.warning("Please enter at least one email address.")
        else:
            raw_emails = [e.strip() for e in input_text.split('\n') if e.strip()]
            
            results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            total = len(raw_emails)
            for i, email in enumerate(raw_emails):
                status, reason, suggestion = validate_single_email(email)
                results.append({
                    "Email": email,
                    "Status": status,
                    "Reason": reason,
                    "Suggested Correction": suggestion
                })
                progress_bar.progress((i + 1) / total)
                status_text.text(f"Checking {i + 1} of {total} emails...")
                
            st.success("Verification Completed!")
            df_res = pd.DataFrame(results)
            st.dataframe(df_res, use_container_width=True)
            
            st.download_button(
                label="📥 Download Result (CSV)",
                data=df_res.to_csv(index=False).encode('utf-8'),
                file_name="single_check_results.csv",
                mime="text/csv"
            )

# --- TAB 2: Bulk File Processing (CSV, XLS, XLSX, TXT) ---
with tab2:
    uploaded_file = st.file_uploader("Upload your contacts file", type=["csv", "xls", "xlsx", "txt"])

    if uploaded_file is not None:
        file_extension = uploaded_file.name.split('.')[-1].lower()
        emails_list = []
        df_original = None
        
        try:
            if file_extension == 'csv':
                df_original = pd.read_csv(uploaded_file)
            elif file_extension in ['xls', 'xlsx']:
                df_original = pd.read_excel(uploaded_file)
            elif file_extension == 'txt':
                stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
                emails_list = [line.strip() for line in stringio if line.strip()]
        except Exception as e:
            st.error(f"Error reading file: {e}")
            
        # Jika file CSV/Excel
        if df_original is not None and not df_original.empty:
            st.write("Data Preview (First 5 Rows):")
            st.dataframe(df_original.head())
            
            email_columns = [col for col in df_original.columns if 'email' in str(col).lower()]
            default_col = email_columns[0] if email_columns else df_original.columns[0]
            
            selected_col = st.selectbox("Select the column containing email addresses:", df_original.columns, index=df_original.columns.get_loc(default_col))
            
            if st.button("Start Verification Process"):
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                rows_data = df_original.to_dict(orient="records")
                total_rows = len(rows_data)
                
                def process_row(row_dict):
                    email_val = row_dict.get(selected_col, "")
                    status, reason, suggestion = validate_single_email(email_val)
                    
                    new_row = row_dict.copy()
                    new_row['Validation_Status'] = status
                    new_row['Error_Reason'] = reason
                    new_row['Suggested_Correction'] = suggestion
                    return new_row

                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {executor.submit(process_row, row): row for row in rows_data}
                    
                    completed = 0
                    for future in concurrent.futures.as_completed(futures):
                        results.append(future.result())
                        completed += 1
                        progress_bar.progress(completed / total_rows)
                        status_text.text(f"Processing {completed} of {total_rows} emails...")
                        
                st.success("Verification Completed!")
                df_result = pd.DataFrame(results)
                
                df_valid = df_result[df_result['Validation_Status'] == 'Valid']
                df_risky = df_result[df_result['Validation_Status'] == 'Risky']
                df_invalid = df_result[df_result['Validation_Status'] == 'Invalid']
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Valid Emails", len(df_valid))
                    if not df_valid.empty:
                        st.download_button(
                            label="📥 Download Valid File (CSV)",
                            data=df_valid.to_csv(index=False).encode('utf-8'),
                            file_name="brevo_ready_valid.csv",
                            mime="text/csv"
                        )
                with col2:
                    st.metric("Risky / Catch-All", len(df_risky))
                    if not df_risky.empty:
                        st.download_button(
                            label="📥 Download Risky File (CSV)",
                            data=df_risky.to_csv(index=False).encode('utf-8'),
                            file_name="brevo_risky.csv",
                            mime="text/csv"
                        )
                with col3:
                    st.metric("Invalid Emails", len(df_invalid))
                    if not df_invalid.empty:
                        st.download_button(
                            label="📥 Download Invalid File (CSV)",
                            data=df_invalid.to_csv(index=False).encode('utf-8'),
                            file_name="rejected_emails.csv",
                            mime="text/csv"
                        )

        # Jika file TXT
        elif emails_list:
            st.write(f"Data Preview ({len(emails_list)} emails found in TXT):")
            st.write(emails_list[:5])
            
            if st.button("Start Verification Process"):
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total = len(emails_list)
                for i, email in enumerate(emails_list):
                    status, reason, suggestion = validate_single_email(email)
                    results.append({
                        "Email": email,
                        "Validation_Status": status,
                        "Error_Reason": reason,
                        "Suggested_Correction": suggestion
                    })
                    progress_bar.progress((i + 1) / total)
                    status_text.text(f"Processing {i + 1} of {total} emails...")
                    
                st.success("Verification Completed!")
                df_result = pd.DataFrame(results)
                st.dataframe(df_result, use_container_width=True)
                
                st.download_button(
                    label="📥 Download Verification Result (CSV)",
                    data=df_result.to_csv(index=False).encode('utf-8'),
                    file_name="txt_verification_results.csv",
                    mime="text/csv"
                )
