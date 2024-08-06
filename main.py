from fastapi import FastAPI, HTTPException, File, UploadFile
from pydantic import BaseModel
from dotenv import load_dotenv
import boto3
import os
import time
import uuid
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session
from fastapi import Depends
import uuid
import json
import boto3
import os
import logging
# Load environment variables
load_dotenv()

app = FastAPI()
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
# Database setup
DATABASE_URL = f"postgresql://{os.getenv('RDS_DB_USER')}:{os.getenv('RDS_DB_PASSWORD')}@{os.getenv('RDS_DB_HOST')}:{os.getenv('RDS_DB_PORT')}/{os.getenv('RDS_DB_NAME')}"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(String, primary_key=True, index=True)
    analysis = Column(Text)
    summary = Column(Text)

Base.metadata.create_all(bind=engine)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class ChatRequest(BaseModel):
    user_message: str

class SummaryRequest(BaseModel):
    pass

class AnalysisRequest(BaseModel):
    # This can be empty if we're not expecting any specific input
    pass



# Utility functions
def analyze_text_from_pdf_s3(file_content, filename):
    object_name = str(uuid.uuid4()) + ".pdf"
    
    s3 = boto3.client(
        's3',
        aws_access_key_id=os.getenv('aws_access_key'),
        aws_secret_access_key=os.getenv('aws_secret_key'),
        region_name=os.getenv('region_name')
    )
    bucket_name = os.getenv('bucket_name')
    aws_access_key_id=os.getenv('aws_access_key'),
    aws_secret_access_key=os.getenv('aws_secret_key')
    print(aws_access_key_id)
    print(aws_secret_access_key)
    
    # Upload PDF to S3
    s3.put_object(Bucket=bucket_name, Key=object_name, Body=file_content, ContentType='application/pdf')
    print(f"Uploaded to s3://{bucket_name}/{object_name}")

    textract = boto3.client(
        'textract',
        aws_access_key_id=os.getenv('aws_access_key'),
        aws_secret_access_key=os.getenv('aws_secret_key'),
        region_name=os.getenv('region_name')
    )

    response = textract.start_document_analysis(
        DocumentLocation={'S3Object': {'Bucket': bucket_name, 'Name': object_name}},
        FeatureTypes=['FORMS', 'TABLES']
    )

    job_id = response['JobId']
    status = ""
    while status not in ["SUCCEEDED", "FAILED"]:
        response = textract.get_document_analysis(JobId=job_id)
        status = response["JobStatus"]
        print(f"Job status: {status}")
        if status in ["SUCCEEDED", "FAILED"]:
            break
        time.sleep(5)

    if status == "SUCCEEDED":
        documentText = ""
        for item in response["Blocks"]:
            if item["BlockType"] == "LINE":
                documentText += item["Text"] + " "
        documentText = documentText.replace(chr(34), '')
        documentText = documentText.replace(chr(39), '')
        s3.delete_object(Bucket=bucket_name, Key=object_name)
        print(f"Deleted s3://{bucket_name}/{object_name}")
        return documentText
    else:
        raise Exception("Document analysis failed.")


import os
import json
import boto3

class ClaudeAnalyzer:
    def __init__(self):
        self.AWS_KEY = os.getenv('aws_access_key')
        self.AWS_SECRET_KEY = os.getenv('aws_secret_key')
        self.bedrock_runtime = boto3.client(
            service_name='bedrock-runtime',
            region_name='us-east-1',
            aws_access_key_id=self.AWS_KEY,
            aws_secret_access_key=self.AWS_SECRET_KEY
        )
        self.modelId = "anthropic.claude-3-5-sonnet-20240620-v1:0"

    def invoke_claude(self, prompt):
        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.3,
                "top_p": 0.9
            })
            
            response = self.bedrock_runtime.invoke_model(body=body, modelId=self.modelId, accept="application/json", contentType="application/json")
            response_body = json.loads(response.get('body').read())
            result = response_body['content'][0]['text']
            return result
        
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            return None

    def summary(self, text):
        prompt = f"Analyze the following data and provide a 3-4 line summary: {text}"
        return self.invoke_claude(prompt)

    def chat(self, user_message, context):
        prompt = f"Context: {context}\n\nAnalyze the following information and answer the query based only on the provided information, including medical terms. Do not generate an answer on your own.\n\nUser Message: {user_message}"
        return self.invoke_claude(prompt)

    def analyze(self, pdf_file):
        file_content = pdf_file.file.read()
        text = analyze_text_from_pdf_s3(file_content, pdf_file.filename)
        if len(text) == 0:
            return ""
        else:
            prompt = f"Analyze the following medical reports extracted from the PDF and information extracted from images. Merge the information and provide a detailed, structured analysis without adding a summary: {text}"
            return self.invoke_claude(prompt)

    def get_claude_response(self, info, query):
        prompt = f"Analyze the following information and answer the query based only on the provided information, including medical terms. Don't generate an answer on your own: {info}\n\nUser Query: {query}"
        return self.invoke_claude(prompt)
    
@app.post("/analyze-text-from-pdf/")
async def analyze_text_from_pdf(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        analyzer = ClaudeAnalyzer()
        text = analyzer.analyze(file)
        
        # Generate a unique ID for this analysis
        analysis_id = str(uuid.uuid4())
        
        # Store the result in the database
        db_item = AnalysisResult(id=analysis_id, analysis=text)
        db.add(db_item)
        db.commit()
        
        return {"text": text, "analysis_id": analysis_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/summary/")
async def summary(db: Session = Depends(get_db)):
    try:
        logger.debug("Received request for summary")
        
        # Get the most recent analysis result
        db_item = db.query(AnalysisResult).order_by(AnalysisResult.id.desc()).first()
        
        if not db_item or not db_item.analysis:
            logger.error("No analysis result found")
            raise HTTPException(status_code=400, detail="No analysis result found. Please upload and analyze a PDF first.")

        analyzer = ClaudeAnalyzer()
        summary_text = analyzer.summary(db_item.analysis)
        
        # Update the database with the summary
        db_item.summary = summary_text
        db.commit()
        
        logger.debug(f"Generated summary: {summary_text[:100]}...")  # Log first 100 chars of summary
        return {"summary": summary_text}
    except Exception as e:
        db.rollback()
        logger.error(f"Error generating summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/")
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    try:
        analyzer = ClaudeAnalyzer()
        
        # Get the most recent analysis result
        db_item = db.query(AnalysisResult).order_by(AnalysisResult.id.desc()).first()
        
        if not db_item:
            raise HTTPException(status_code=400, detail="No analysis result found. Please upload and analyze a PDF first.")
        
        context = f"Analysis: {db_item.analysis}\nSummary: {db_item.summary or ''}"
        response_text = analyzer.chat(request.user_message, context)
        return {"response": response_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))