import os
import uuid
import time
import json
import logging
from typing import Dict, Any

import boto3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, File, UploadFile, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# FastAPI app initialization
app = FastAPI()

# Database setup
DATABASE_URL = f"postgresql://{os.getenv('RDS_DB_USER')}:{os.getenv('RDS_DB_PASSWORD')}@{os.getenv('RDS_DB_HOST')}:{os.getenv('RDS_DB_PORT')}/{os.getenv('RDS_DB_NAME')}"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class NewAnalysisResult(Base):
    __tablename__ = "new_analysis_results"
    id = Column(String, primary_key=True, index=True)
    analysis = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

# Pydantic models
class ChatRequest(BaseModel):
    user_message: str

class AnalysisRequest(BaseModel):
    pass

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Utility functions
def get_aws_client(service_name: str) -> boto3.client:
    return boto3.client(
        service_name,
        aws_access_key_id=os.getenv('aws_access_key'),
        aws_secret_access_key=os.getenv('aws_secret_key'),
        region_name=os.getenv('region_name')
    )

def upload_to_s3(file_content: bytes, object_name: str) -> None:
    s3 = get_aws_client('s3')
    bucket_name = os.getenv('bucket_name')
    s3.put_object(Bucket=bucket_name, Key=object_name, Body=file_content, ContentType='application/pdf')
    logger.info(f"Uploaded to s3://{bucket_name}/{object_name}")

def delete_from_s3(object_name: str) -> None:
    s3 = get_aws_client('s3')
    bucket_name = os.getenv('bucket_name')
    s3.delete_object(Bucket=bucket_name, Key=object_name)
    logger.info(f"Deleted s3://{bucket_name}/{object_name}")

def analyze_document(object_name: str) -> str:
    textract = get_aws_client('textract')
    bucket_name = os.getenv('bucket_name')

    response = textract.start_document_analysis(
        DocumentLocation={'S3Object': {'Bucket': bucket_name, 'Name': object_name}},
        FeatureTypes=['FORMS', 'TABLES']
    )

    job_id = response['JobId']
    while True:
        response = textract.get_document_analysis(JobId=job_id)
        status = response["JobStatus"]
        logger.info(f"Job status: {status}")
        if status in ["SUCCEEDED", "FAILED"]:
            break
        time.sleep(5)

    if status == "SUCCEEDED":
        return " ".join(item["Text"] for item in response["Blocks"] if item["BlockType"] == "LINE")
    else:
        raise Exception("Document analysis failed.")

def analyze_text_from_pdf_s3(file_content: bytes, filename: str) -> str:
    object_name = f"{uuid.uuid4()}.pdf"
    upload_to_s3(file_content, object_name)
    
    try:
        document_text = analyze_document(object_name)
        return document_text.replace(chr(34), '').replace(chr(39), '')
    finally:
        delete_from_s3(object_name)

class ClaudeAnalyzer:
    def __init__(self):
        self.bedrock_runtime = get_aws_client('bedrock-runtime')
        self.model_id = "anthropic.claude-3-5-sonnet-20240620-v1:0"

    def invoke_claude(self, prompt: str) -> str:
        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "top_p": 0.9
            })
            
            response = self.bedrock_runtime.invoke_model(body=body, modelId=self.model_id, accept="application/json", contentType="application/json")
            response_body = json.loads(response.get('body').read())
            return response_body['content'][0]['text']
        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")
            return None

    def chat(self, user_message: str, context: str) -> str:
        prompt = f"Context: {context}\n\nAnalyze the following information and answer the query based only on the provided information, including medical terms. Do not generate an answer on your own.\n\nUser Message: {user_message}"
        return self.invoke_claude(prompt)

    def analyze_and_summarize(self, pdf_file: UploadFile) -> str:
        file_content = pdf_file.file.read()
        text = analyze_text_from_pdf_s3(file_content, pdf_file.filename)
        if not text:
            return ""
        analysis_prompt = f"Analyze the following medical reports extracted from the PDF and information extracted from images. Merge the information and provide a detailed, structured analysis. After completing the analysis, provide a 3-4 line summary under the heading **AI GENERATED SUMMARY**: {text}"
        return self.invoke_claude(analysis_prompt)

# API endpoints
@app.post("/analyze-text-from-pdf/")
async def analyze_text_from_pdf(file: UploadFile = File(...), db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        analyzer = ClaudeAnalyzer()
        result = analyzer.analyze_and_summarize(file)
        
        analysis_id = str(uuid.uuid4())
        new_analysis = NewAnalysisResult(id=analysis_id, analysis=result)
        db.add(new_analysis)
        db.commit()
        
        return {"result": result, "analysis_id": analysis_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/")
async def chat(request: ChatRequest, db: Session = Depends(get_db)) -> Dict[str, str]:
    try:
        analyzer = ClaudeAnalyzer()
        
        new_analysis = db.query(NewAnalysisResult).order_by(NewAnalysisResult.created_at.desc()).first()
        
        if not new_analysis:
            raise HTTPException(status_code=400, detail="No analysis result found. Please upload and analyze a PDF first.")
        
        context = f"Analysis and Summary: {new_analysis.analysis}"
        response_text = analyzer.chat(request.user_message, context)
        return {"response": response_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
