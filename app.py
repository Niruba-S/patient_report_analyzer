import streamlit as st
import os
from dotenv import load_dotenv
import tempfile
import hashlib
import psycopg2
import base64
import requests
import re
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import secrets
import random
import string
from botocore.exceptions import ClientError
import os
import boto3

import os
import tempfile
import requests

load_dotenv()


# Set up logging
logging.basicConfig(level=logging.INFO)

BACKEND_URL = "http://localhost:8000"


def analyze_pdf(file):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(file.getvalue())
            tmp_file_path = tmp_file.name

        # File is now closed, we can safely open it for the request
        with open(tmp_file_path, 'rb') as pdf_file:
            files = {'file': pdf_file}
            response = requests.post(f"{BACKEND_URL}/analyze-text-from-pdf/", files=files)

        # After the request is done, we can safely remove the file
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)

        if response.status_code == 200:
            return response.json()['text']
        else:
            st.error(f"Error analyzing PDF: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Error processing PDF: {str(e)}")
        return None
    finally:
        # Ensure the file is deleted even if an exception occurs
        if 'tmp_file_path' in locals() and os.path.exists(tmp_file_path):
            try:
                os.remove(tmp_file_path)
            except Exception as e:
                st.error(f"Error deleting temporary file: {str(e)}")
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def get_summary():
    try:
        logger.debug(f"Sending request to {BACKEND_URL}/summary/")
        response = requests.post(f"{BACKEND_URL}/summary/")
        logger.debug(f"Received response with status code: {response.status_code}")
        response.raise_for_status()
        summary = response.json()['summary']
        logger.debug(f"Received summary: {summary[:100]}...")  # Log first 100 chars of summary
        return summary
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting summary: {str(e)}")
        st.error(f"Error getting summary: {str(e)}")
        return None

def chat_with_bot(user_message):
    data = {"user_message": user_message}
    response = requests.post(f"{BACKEND_URL}/chat/", json=data)
    if response.status_code == 200:
        return response.json()['response']
    else:
        st.error("Error chatting with bot")
        return None

# Database connection function
def get_db_connection():
    try:
        return psycopg2.connect(
            dbname=os.getenv("RDS_DB_NAME"),
            user=os.getenv("RDS_DB_USER"),
            password=os.getenv("RDS_DB_PASSWORD"),
            host=os.getenv("RDS_DB_HOST"),
            port=os.getenv("RDS_DB_PORT", 5432)
        )
    except Exception as e:
        logging.error(f"Error connecting to database: {e}")
        return None
   
# Create users table
logging.info(f"Connecting to database: {os.getenv('RDS_DB_NAME')} on host: {os.getenv('RDS_DB_HOST')}")
def create_users_table():
    conn = get_db_connection()
    if not conn:
        return
    
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL
            )
        """)
        conn.commit()
        logging.info("Users table created or already exists")
    except Exception as e:
        logging.error(f"Error creating users table: {e}")
    finally:
        cur.close()
        conn.close()

# Call this function at the start of your app
create_users_table()

def add_logo(image_url, image_size="100px"):
    try:
        response = requests.get(image_url)
        img_data = response.content
        b64_encoded = base64.b64encode(img_data).decode()
        logo_html = f"""
            <div style=" top: 10px; left: 10px; width: {image_size}; height: auto; z-index: 1000;">
                <img src="data:image/png;base64,{b64_encoded}" style="width: {image_size}; height: auto;">
            </div>
        """
        st.markdown(logo_html, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Error loading logo image: {e}")

def set_custom_style():
    st.markdown("""
        <style>
        .stTextInput > div > div > input {
            width: 300px;
        }
        .form-container {
            display: flex;
            flex-direction: column;
        }
        .form-container .stButton {
            align-self: center;
        }
        </style>
    """, unsafe_allow_html=True)

def is_valid_email(email):
    regex = r'^\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    return re.match(regex, email)

def is_valid_password(password):
    if len(password) < 8:
        return False
    if not re.search(r'\d', password):
        return False
    if not re.search(r'[A-Z]', password):
        return False
    if not re.search(r'[a-z]', password):
        return False
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False
    return True

def signup(username, email, password, confirm_password):
    if not is_valid_email(email):
        st.error("Please enter a valid email address")
        return False
    elif not is_valid_password(password):
        st.error("Password must be at least 8 characters long and include a number, an uppercase letter, a lowercase letter, and a special character")
        return False
    elif password != confirm_password:
        st.error("Passwords do not match")
        return False
    elif not username or not email or not password:
        st.error("Please fill in all fields")
        return False
    else:
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        conn = get_db_connection()
        if not conn:
            st.error("Unable to connect to the database")
            return False
        
        cur = conn.cursor()
        
        try:
            cur.execute(
                "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                (username, email, hashed_password)
            )
            conn.commit()
            st.success("You have successfully signed up!")
            if send_welcome_email(email, username):
                logging.info(f"Welcome email sent to {email}")
            else:
                logging.error(f"Failed to send welcome email to {email}")
            
            return True
        except psycopg2.IntegrityError:
            st.error("Username or email already exists")
            return False
        except Exception as e:
            logging.error(f"Error during signup: {e}")
            st.error("An error occurred during signup")
            return False
        finally:
            cur.close()
            conn.close()
            
def verify_login(email, password):
    conn = get_db_connection()
    if not conn:
        return False
    
    cur = conn.cursor()
    
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    
    try:
        cur.execute("SELECT email FROM users WHERE email=%s AND password=%s", (email, hashed_password))
        user = cur.fetchone()
        return user[0] if user else None
    except Exception as e:
        logging.error(f"Error verifying login: {e}")
        return None
    finally:
        cur.close()
        conn.close()

def generate_random_password(length=12):
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(random.choice(characters) for i in range(length))

def reset_password(email):
    conn = get_db_connection()
    if not conn:
        st.error("Unable to connect to the database")
        return False
    
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT email FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        if user:
            new_password = generate_random_password()
            hashed_password = hashlib.sha256(new_password.encode()).hexdigest()
            
            cur.execute("UPDATE users SET password=%s WHERE email=%s", (hashed_password, email))
            conn.commit()
            
            if send_reset_email(email, new_password):
                return True
            else:
                st.error("Failed to send reset email")
                return False
        else:
            st.error("Email not found")
            return False
    except Exception as e:
        logging.error(f"Error during password reset: {e}")
        st.error("An error occurred during password reset")
        return False
    finally:
        cur.close()
        conn.close()

def send_reset_email(email, new_password):
    sender_email = os.getenv("SENDER_EMAIL")
    
    message = MIMEMultipart("alternative")
    message["Subject"] = "Password Reset"
    message["From"] = sender_email
    message["To"] = email

    text = f"""
    Dear User,Your temporary password is: {new_password}
    For security reasons, please log in and change this password immediately.
    """

    html = f"""
    <p>Dear User, Your temporary password is: <strong>{new_password}</strong><br>
    For security reasons, please log in and change this password immediately.<br>
    </p>
    """
    part1 = MIMEText(text, "plain")
    part2 = MIMEText(html, "html")

    message.attach(part1)
    message.attach(part2)

    # AWS credentials should be set in environment variables or AWS configuration files
    session = boto3.Session(
        aws_access_key_id=os.getenv('aws_access_key'),
        aws_secret_access_key=os.getenv('aws_secret_key'),
        region_name=os.getenv('region_name')
    )
    
    client = session.client('ses')

    try:
        response = client.send_raw_email(
            Source=sender_email,
            Destinations=[email],
            RawMessage={'Data': message.as_string()}
        )
    except ClientError as e:
        logging.error(f"Error sending reset email to {email}: {e.response['Error']['Message']}")
        return False
    else:
        logging.info(f"Email sent! Message ID: {response['MessageId']}")
        return True
    


# Initialize session state variables
if "conversation" not in st.session_state:
    st.session_state.conversation = []
if "uploaded_file" not in st.session_state:
    st.session_state.uploaded_file = None
if "text" not in st.session_state:
    st.session_state.text = " "
if "page" not in st.session_state:
    st.session_state.page = "login"
if "Image_text" not in st.session_state:
    st.session_state.Image_text = ""
if "sum" not in st.session_state:
    st.session_state.sum = ""
if "content_generated" not in st.session_state:
    st.session_state.content_generated = False
if "sidebar_message" not in st.session_state:
    st.session_state.sidebar_message = "Welcome!"
if "login_success" not in st.session_state:
    st.session_state.login_success = False
if "user_email" not in st.session_state:
    st.session_state.user_email = None
    
    
    
def get_user_name(email):
    conn = get_db_connection()
    if not conn:
        return None
    
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT username FROM users WHERE email = %s", (email,))
        result = cur.fetchone()
        return result[0] if result else None
    except Exception as e:
        logging.error(f"Error fetching user name for email {email}: {e}")
        return None
    finally:
        cur.close()
        conn.close()

    
if st.session_state.login_success and st.session_state.user_email:
    user_name = get_user_name(st.session_state.user_email)
    if user_name:
        st.session_state.sidebar_message = f"Welcome, {user_name}!"
    
def login_page():
    add_logo("https://www.goml.io/wp-content/smush-webp/2023/10/GoML_logo.png.webp", image_size="200px")
    st.title("Claude Powered Patient Lab Report Analyzer")
    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    with tab1:
        col1, col2 = st.columns([1, 1])
        with col1:
            with st.form(key='login_form'):
                email = st.text_input("Email", key="login_email")
                password = st.text_input("Password", type="password", key="login_password")
                
                col1, col2 = st.columns(2)
                with col1:
                    login_button = st.form_submit_button(label='Login')
                with col2:
                    forgot_password_button = st.form_submit_button(label='Forgot Password')
                
                if login_button:
                    login_result = verify_login(email, password)
                    if login_result:
                        st.session_state.page = "home"
                        st.session_state.login_success = True
                        st.session_state.user_email = login_result
                        st.rerun()
                    else:
                        st.error("Invalid email or password")
                
                if forgot_password_button:
                    if email:
                        if reset_password(email):
                            st.success(f"New password sent to {email}. Please check your email.")
                        else:
                            st.error("Failed to reset password. Please try again.")
                    else:
                        st.error("Please enter your email to reset your password")
        
        with col2:
            st.write("")
            st.write("")
    
    with tab2:
        col1, col2 = st.columns([1, 1])
        with col1:
            with st.form(key='signup_form'):
                signup_username = st.text_input("Username", key="signup_username")
                signup_email = st.text_input("Email", key="signup_email")
                signup_password = st.text_input("Password", type="password", key="signup_password")
                signup_confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm_password")
                signup_button = st.form_submit_button(label='Sign Up')
                
                if signup_button:
                    if signup(signup_username, signup_email, signup_password, signup_confirm_password):
                        st.session_state.page = "home"
                        st.session_state.login_success = True
                        st.rerun()
        
        with col2:
            st.write("")
            st.write("")
            
            
def send_welcome_email(email, username):
    sender_email = os.getenv("SENDER_EMAIL")
    
    message = MIMEMultipart("alternative")
    message["Subject"] = "Welcome to Gen AI Lab Report Analyzer - Let's Get Started!"
    message["From"] = sender_email
    message["To"] = email

    text = f"""
    Dear {username},

    Welcome! Thank you for subscribing to our Gen AI Capability - Lab Report Analyzer on AWS Marketplace. Start exploring insights by uploading your lab reports and asking questions.
 
    For more updates - Please visit https://www.goml.io/
    For assistance, contact subscriptions@goml.io
    
    
    Warm regards,
    
    www.goml.io
    """

    html = f"""
    <html>
    <body>
    <p>Dear {username},</p>

    <p>Welcome! Thank you for subscribing to our Gen AI Capability - Lab Report Analyzer on AWS Marketplace. Start exploring insights by uploading your lab reports and asking questions.</p>
    <p> For more updates - Please visit <a href="https://www.goml.io/">https://www.goml.io/</a></p>
    <p>For assistance, contact subscriptions@goml.io</p>

    <p>Warm regards,<br>
    The GoML Team<br>
    <a href="http://www.goml.io">www.goml.io</a></p>
    </body>
    </html>
    """

    part1 = MIMEText(text, "plain")
    part2 = MIMEText(html, "html")

    message.attach(part1)
    message.attach(part2)

    session = boto3.Session(
        aws_access_key_id=os.getenv('aws_access_key'),
        aws_secret_access_key=os.getenv('aws_secret_key'),
        region_name=os.getenv('region_name')
    )
    
    client = session.client('ses')

    try:
        response = client.send_raw_email(
            Source=sender_email,
            Destinations=[email],
            RawMessage={'Data': message.as_string()}
        )
    except ClientError as e:
        logging.error(f"Error sending welcome email to {email}: {e.response['Error']['Message']}")
        return False
    else:
        logging.info(f"Welcome email sent! Message ID: {response['MessageId']}")
        return True
            

def reset_password_page():
    display_sidebar() 
    st.title("Reset Password")
    user_email = st.session_state.get('user_email')
    if user_email:
        user_name = get_user_name(user_email)
        if user_name:
            st.markdown(f"Hi {user_name}! You can reset your password below.")
        else:
            st.markdown(f"Hi! You can reset your password below.")
    col1, col2 = st.columns([2, 1])
    with col1:
        email = st.text_input("Email", key="reset_email")
        
        new_password = st.text_input("New Password", type="password", key="new_password")
        
        confirm_password = st.text_input("Confirm New Password", type="password", key="confirm_password")
        
        if st.button("Reset Password",key="reset_password_button"):
            if not email or not new_password or not confirm_password:
                st.error("Please fill in all fields")
            elif new_password != confirm_password:
                st.error("Passwords do not match")
            elif not is_valid_password(new_password):
                st.error("Password must be at least 8 characters long and include a number, an uppercase letter, a lowercase letter, and a special character")
            else:
                if update_password(email, new_password):
                    st.success("Password successfully reset. You can now log in with your new password.")
                else:
                    st.error("Failed to reset password. Please try again.")
        st.write("")
        st.write("")
        
        # Add the "Go Home" button at the bottom left
        if st.button("🏠 Go Home"):
            st.session_state.page = "home"
            st.rerun()
    with col2:
        st.write("")  # This empty column helps to make the layout more compact

def update_password(email, new_password):
    conn = get_db_connection()
    if not conn:
        return False
    
    cur = conn.cursor()
    
    try:
        hashed_password = hashlib.sha256(new_password.encode()).hexdigest()
        
        cur.execute("UPDATE users SET password = %s WHERE email = %s", (hashed_password, email))
        
        if cur.rowcount == 0:
            logging.error(f"No user found with email: {email}")
            return False
        
        conn.commit()
        logging.info(f"Password updated successfully for email: {email}")
        return True
    except Exception as e:
        logging.error(f"Error updating password for email {email}: {e}")
        return False
    finally:
        cur.close()
        conn.close()
def home_page():
    
    st.markdown("<h3 style='font-size: 25px;'>Upload scanned images or PDFs of patient lab reports to get instant insights and answers to your queries</h3>", unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("Choose a file", type=["pdf"])
    if uploaded_file and st.button("ANALYZE"):
        with st.spinner("ANALYZING"):
            try:
                text = analyze_pdf(uploaded_file)
                if text:
                    st.session_state.text = text
                    st.session_state.uploaded_file = uploaded_file
                    st.session_state.content_generated = True
            except Exception as e:
                st.error(f"Error processing PDF: {e}")
    
    if st.session_state.content_generated:
        st.header("REPORT")
        st.write(st.session_state.text)

        st.header("AI GENERATED SUMMARY")
        if 'sum' not in st.session_state or not st.session_state.sum:
            st.session_state.sum = get_summary()
        st.write(st.session_state.sum)

        # Move chatbot to sidebar when content is generated
        st.sidebar.header("Chatbot🤖")
        user_input = st.sidebar.text_input("Type your message here...", key="chat_input")
        if user_input:
            bot_response = chat_with_bot(user_input)
            if bot_response:
                st.session_state.conversation.insert(0, {"role": "assistant", "content": bot_response})
                st.session_state.conversation.insert(0, {"role": "user", "content": user_input})
        
        # Display conversation history in sidebar (recent conversations on top)
        for i in range(0, len(st.session_state.conversation), 2):
            if i+1 < len(st.session_state.conversation):
                user_message = st.session_state.conversation[i]
                bot_message = st.session_state.conversation[i+1]
                
                st.sidebar.write(f"**You:** {user_message['content']}")
                st.sidebar.write(f"**Bot:** {bot_message['content']}")
            else:
                user_message = st.session_state.conversation[i]
                st.sidebar.write(f"**You:** {user_message['content']}")
            
            st.sidebar.write("__________________________________________________________________________________________________________________________________________")
def set_wide_layout():
    st.set_page_config(layout="wide")
    st.markdown(
        """
    <style>
        section[data-testid="stSidebar"] {
            width: 400px !important;
        }
    </style>
    """,
        unsafe_allow_html=True,
    )
def display_sidebar():
    st.sidebar.header(st.session_state.sidebar_message)
    
    # Profile button at the very top
    if st.sidebar.button("👤 Profile", key="profile_button"):
        st.session_state.show_account_menu = not st.session_state.get('show_account_menu', False)
    
    # Show account menu if the profile button was clicked
    if st.session_state.get('show_account_menu', False):
        st.sidebar.subheader("Account Options")
        if st.sidebar.button("Reset Password"):
            st.session_state.page = "reset_password"
            st.rerun()
        if st.sidebar.button("   Logout  "):
            # Reset all session state variables
            st.session_state.page = "login"
            st.session_state.login_success = False
            st.session_state.conversation = []
            st.session_state.uploaded_file = None
            st.session_state.text = " "
            st.session_state.Image_text = ""
            st.session_state.sum = ""
            st.session_state.content_generated = False
            st.session_state.user_email = None
            st.rerun()
        if st.sidebar.button("  Close Menu  "):
            st.session_state.show_account_menu = False
            st.rerun()
def main():
    if st.session_state.get('login_success'):
        set_wide_layout()
    
    # Sidebar width CSS
    st.markdown(
        """
    <style>
        section[data-testid="stSidebar"] {
            width: 400px !important;
        }
    </style>
    """,
        unsafe_allow_html=True,
    )
    
    if st.session_state.page == "login":
        login_page()
    elif st.session_state.page == "reset_password":
        reset_password_page()
    elif st.session_state.page == "home":
        if st.session_state.login_success:
            display_sidebar()
            # Call home_page() function
            home_page()
        else:
            st.warning("Please log in to access the home page.")
            st.session_state.page = "login"
            st.rerun()
    

if __name__ == "__main__":
    main()