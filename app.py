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


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
# Set up logging
logging.basicConfig(level=logging.INFO)

BACKEND_URL = "https://ffx5lzqebmrnwd37jfmyl4xeve0bcmvh.lambda-url.us-east-1.on.aws/"
access_key = os.environ.get("aws_access_key")
secret_key = os.environ.get("aws_secret_key")

def get_entitlements(customer_id : str):
    try:
       
        marketplace_client = boto3.client(
            "marketplace-entitlement",
            region_name="us-east-1",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        entitlements = marketplace_client.get_entitlements(
            ProductCode="db70sghlx0y4s77pfepvtx74q",
            Filter={"CUSTOMER_IDENTIFIER": [customer_id]},
        )
        
        return {
            "status": "success",
            "entitlements": entitlements,
        }
            
    except Exception as e:
        return {"error": str(e)}
        
def submit_usage_record(customer_identifier, product_code, dimension, quantity):
    


    # Define the usage record
    current_time = datetime.utcnow()
    valid_timestamp = current_time.replace(microsecond=0)
    usage_record = [
        {
            'Timestamp': valid_timestamp,
            'CustomerIdentifier': customer_identifier,
            'Dimension': dimension,
            'Quantity': quantity
        }
    ]

    # Initialize the AWS Marketplace Metering client
    marketplace_client = boto3.client(
        'meteringmarketplace',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1"
    )

    # Send the usage record to AWS Marketplace
    try:
        response = marketplace_client.batch_meter_usage(
            UsageRecords=usage_record,
            ProductCode=product_code
        )
        print("Usage record submitted successfully:", response)
        return response
    except Exception as e:
        print("Error submitting usage record:", str(e))
        return None

# Example usage of the function
response = submit_usage_record(
    customer_identifier='Q7Zqhr53B3i',
    product_code='db70sghlx0y4s77pfepvtx74q',
    dimension='UsageBased',
    quantity=1
)

def get_marketplace_customer_id(email):
    print(email)
    conn = get_db_connection()
    if not conn:
        logging.error("Unable to connect to the database")
        return None

    cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM users WHERE email = %s", (email,))
        result = cur.fetchone()
        print(result)
        if not result:
            logging.error(f"No user found with email: {email}")
            return None
        
        user_customer_id = result[0]
        print(user_customer_id)

        cur.execute("SELECT customer_id FROM product_customers WHERE id = %s", (user_customer_id,))
        result = cur.fetchone()
        
        if not result:
            logging.error(f"No product customer found for user customer_id: {user_customer_id}")
            return None
        print(result[0])
        return result[0] 
    # This is the marketplace customer_id
    except Exception as e:
        logging.error(f"Error retrieving marketplace customer ID: {e}")
        return None
    finally:
        cur.close()
        conn.close()



def analyze_and_summarize_pdf(file):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(file.getvalue())
            tmp_file_path = tmp_file.name

        with open(tmp_file_path, 'rb') as pdf_file:
            files = {'file': pdf_file}
            response = requests.post(f"{BACKEND_URL}/analyze-text-from-pdf/", files=files)

        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)

        if response.status_code == 200:
            result = response.json()
            return result['result'], result['analysis_id']
        else:
            st.error(f"Error analyzing PDF: {response.status_code}")
            return None, None
    except Exception as e:
        st.error(f"Error processing PDF: {str(e)}")
        return None, None
    finally:
        if 'tmp_file_path' in locals() and os.path.exists(tmp_file_path):
            try:
                os.remove(tmp_file_path)
            except Exception as e:
                st.error(f"Error deleting temporary file: {str(e)}")




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
                password VARCHAR(255) NOT NULL,
                customer_id INTEGER,
                CONSTRAINT fk_id1 FOREIGN KEY (customer_id) 
                REFERENCES product_customers(id)
            )
        """)
        conn.commit()
        logging.info("Users table created or already exists")
    except Exception as e:
        logging.error(f"Error creating users table: {e}")
    finally:
        cur.close()
        conn.close()

def create_product_customers_table():
    conn = get_db_connection()
    if not conn:
        return

    cur = conn.cursor()
    try:
        # Create the product_customers table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS product_customers (
                id SERIAL PRIMARY KEY,
                product_code VARCHAR(100) NOT NULL,
                customer_id VARCHAR(100) UNIQUE NOT NULL,
                customer_aws_account_id VARCHAR(100) NOT NULL
            )
        """)
        
        conn.commit()
        logging.info("Product customers table created or already exists")
    except Exception as e:
        conn.rollback()
        logging.error(f"Error creating product_customers table: {e}")
    finally:
        cur.close()
        conn.close()

def add_unique_constraint_to_customer_id():
    conn = get_db_connection()
    if not conn:
        return

    cur = conn.cursor()
    try:
        cur.execute("""
            ALTER TABLE users
            ADD CONSTRAINT unique_customer_id UNIQUE (customer_id);
        """)
        conn.commit()
        logging.info("UNIQUE constraint added to customer_id in users table")
    except psycopg2.Error as e:
        conn.rollback()
        logging.error(f"Error adding UNIQUE constraint to customer_id: {e}")
    finally:
        cur.close()
        conn.close()

# Call these functions at the start of your app
create_product_customers_table()
create_users_table()
add_unique_constraint_to_customer_id()



print(st.query_params)
    

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
    atrs = st.query_params.get("atrs")
    if not atrs:
        st.error("This application is available only on AWS Market Place. Please try to sign up through AWS Marketplace portal")
        return False
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
        
        # Get the atrs value from URL query parameters
        atrs = st.query_params.get("atrs")
        if not atrs:
            st.error("Invalid signup link. Please use the correct URL.")
            return False

        # Ensure atrs is converted to integer
        try:
            customer_id = int(atrs)
        except ValueError:
            st.error("Invalid customer ID format.")
            return False

        conn = get_db_connection()
        if not conn:
            st.error("Unable to connect to the database")
            return False
        
        cur = conn.cursor()
        
        try:
            # Check if email already exists
            cur.execute(
                "SELECT email FROM users WHERE email = %s",
                (email,)
            )
            existing_email = cur.fetchone()
            if existing_email:
                st.error("Email already exists")
                return False

            # Check if the customer_id exists in product_customers table
            cur.execute(
                "SELECT id FROM product_customers WHERE id = %s",
                (customer_id,)
            )
            if cur.fetchone() is None:
                st.error("This customer ID does not exist in the product_customers table.")
                return False

            # If all checks pass, proceed with user insertion
            cur.execute(
                "INSERT INTO users (username, email, password, customer_id) VALUES (%s, %s, %s, %s)",
                (username, email, hashed_password, customer_id)
            )
            conn.commit()
            st.session_state.user_email = email
            st.success("You have successfully signed up!")
            if send_welcome_email(email, username):
                logging.info(f"Welcome email sent to {email}")
            else:
                logging.error(f"Failed to send welcome email to {email}")
            
            return True
        except psycopg2.IntegrityError as e:
            logging.error(f"IntegrityError during signup: {e}")
            st.error(f"An error occurred during signup: {e}")
            return False
        except Exception as e:
            logging.error(f"Error during signup: {e}")
            st.error(f"An unexpected error occurred during signup: {e}")
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

            Welcome, and thank you for subscribing to GoML's Gen AI Capability - Lab Report Analyzer on AWS Marketplace! Log in to gain detailed insights into your lab reports by uploading them and asking questions.

            Click to Login - https://labreportanalyzer.goml.io/

            For more updates - Please visit https://www.goml.io/
            For assistance, contact contact@goml.io

            Warm regards,

            Team GoML
            https://www.goml.io/
            """

    html = f"""
            <html>
            <body>
            <p>Dear {username},</p>

            <p>Welcome, and thank you for subscribing to GoML's Gen AI Capability - Lab Report Analyzer on AWS Marketplace! Log in to gain detailed insights into your lab reports by uploading them and asking questions.</p>

            <p>Click to Login - <a href="https://labreportanalyzer.goml.io/">https://labreportanalyzer.goml.io/</a></p>

            <p>For more updates - Please visit <a href="https://www.goml.io/">https://www.goml.io/</a></p>
            <p>For assistance, contact <a href="mailto:contact@goml.io">contact@goml.io</a></p>

            <p>Warm regards,<br>
            Team GoML<br>
            <a href="https://www.goml.io/">https://www.goml.io/</a></p>
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
                result, analysis_id = analyze_and_summarize_pdf(uploaded_file)
                if result:
                    st.session_state.text = result
                    st.session_state.analysis_id = analysis_id
                    st.session_state.uploaded_file = uploaded_file
                    st.session_state.content_generated = True
            except Exception as e:
                st.error(f"Error processing PDF: {e}")
    
    if st.session_state.content_generated:
        st.markdown("Report Analysis")
        st.write(st.session_state.text)
        customer_id = get_marketplace_customer_id(st.session_state.user_email)
        submit_usage_record(
            customer_id,
            product_code='db70sghlx0y4s77pfepvtx74q',
            dimension='ReportGeneration',
            quantity=1
        )

        # Move chatbot to sidebar when content is generated
        st.sidebar.header("Chatbot🤖")
        user_input = st.sidebar.text_input("Type your message here...", key="chat_input")
        if user_input:
            customer_id = get_marketplace_customer_id(st.session_state.user_email)
            submit_usage_record(
            customer_id,
            product_code='db70sghlx0y4s77pfepvtx74q',
            dimension='UsageBased',
            quantity=1
            )
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
        customer_id = get_marketplace_customer_id(st.session_state.user_email)

        result = get_entitlements(customer_id)
        
        if result and result["status"] == "success":
                date = result["entitlements"]["ResponseMetadata"]["HTTPHeaders"]["date"]
                st.sidebar.subheader(f"Subscription ends on: {date}")            
        
            
        
        else:
                st.error("Unable to retrieve entitlements.")
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
