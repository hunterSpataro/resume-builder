from flask import Flask, request, jsonify, send_file, render_template, session
from flask_cors import CORS
import os
from dotenv import load_dotenv
import anthropic
import PyPDF2
import docx
from io import BytesIO
import secrets

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Configure CORS
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Accept"],
        "max_age": 3600
    }
})

class ResumeBuilder:
    def __init__(self):
        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise ValueError("CLAUDE_API_KEY not found in environment variables")
        self.client = anthropic.Anthropic(api_key=api_key)

    def extract_text_from_pdf(self, pdf_file):
        """Extract text content from uploaded PDF file"""
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text

    def generate_documents(self, resume_text: str, job_description: str):
        try:
            prompt = f"""Please help me tailor my resume and create a cover letter for a job application.

            Here is my current resume:
            {resume_text}
            
            Here is the job description:
            {job_description}
            
            Please provide a tailored version of my resume with these guidelines:
            • Use existing resume content only, keeping all dates, titles, and company names exactly as shown
            • Begin with name and contact details
            • Include a focused 3-4 line professional summary highlighting relevant experience
            • Reframe achievements to emphasize skills matching the job requirements
            • Maintain all sections from original resume
            • Present most relevant experiences first
            • Use clear, ATS-friendly formatting

            After the resume, please add exactly "COVER LETTER:" on its own line, followed by a professional cover letter with these guidelines:
            • Include standard business letter header with my contact details
            • Open with a warm, professional introduction stating the target role
            • Highlight 2-3 specific achievements from my resume that match the role
            • Show clear understanding of company needs and how my experience addresses them
            • Maintain natural flow between paragraphs
            • Close with clear interest in next steps
            • Write in a professional yet personable tone
            • Keep length around 220 words for main content"""

            message = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}]
            )

            # Split response into resume and cover letter
            full_response = message.content[0].text
            parts = full_response.split('COVER LETTER:')
            
            return {
                'resume': parts[0].strip(),
                'cover_letter': parts[1].strip() if len(parts) > 1 else ''
            }

        except Exception as e:
            app.logger.error(f"Error in generate_documents: {str(e)}")
            return {
                'resume': '',
                'cover_letter': '',
                'error': f"Generation failed: {str(e)}"
            }

builder = ResumeBuilder()

def create_docx(content):
    """Create a DOCX document from content"""
    doc = docx.Document()
    doc.add_paragraph(content)
    return doc

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/generate', methods=['POST', 'OPTIONS'])
def generate():
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        if 'resume' not in request.files:
            return jsonify({'error': 'No resume file uploaded'}), 400
        
        resume_file = request.files['resume']
        job_description = request.form.get('jobDescription', '')
        
        if not job_description:
            return jsonify({'error': 'No job description provided'}), 400
            
        if resume_file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
            
        if not resume_file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'File must be a PDF'}), 400

        try:
            # Extract text from PDF
            resume_text = builder.extract_text_from_pdf(resume_file)
        except Exception as e:
            app.logger.error(f"PDF extraction error: {str(e)}")
            return jsonify({'error': 'Error reading PDF file. Please ensure it is a valid PDF.'}), 400
        
        try:
            # Generate new documents
            result = builder.generate_documents(resume_text, job_description)
        except Exception as e:
            app.logger.error(f"Document generation error: {str(e)}")
            return jsonify({'error': 'Error generating documents. Please try again.'}), 500
        
        if 'error' in result:
            app.logger.error(f"Generation result error: {result['error']}")
            return jsonify({'error': result['error']}), 500
            
        # Store generated documents in session
        session['generated_resume'] = result['resume']
        session['generated_cover'] = result['cover_letter']
        
        return jsonify({'success': True, 'message': 'Documents generated successfully'})
        
    except Exception as e:
        app.logger.error(f"Unexpected error in /generate endpoint: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred. Please try again.'}), 500

@app.route('/download/<doc_type>/docx', methods=['GET'])
def download(doc_type):
    try:
        app.logger.info(f"Download requested for {doc_type}")
        
        if doc_type not in ['resume', 'cover']:
            app.logger.error(f"Invalid document type requested: {doc_type}")
            return jsonify({'error': 'Invalid document type'}), 400
        
        # Get content from session
        content = session.get(f'generated_{doc_type}')
        app.logger.info(f"Retrieved content length: {len(content) if content else 'None'}")
        
        if not content:
            app.logger.error(f"No content found for {doc_type}")
            return jsonify({'error': 'No generated content found'}), 404
        
        # Create DOCX and serve
        doc = create_docx(content)
        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        app.logger.info(f"Successfully created DOCX for {doc_type}")
        
        return send_file(
            buffer,
            download_name=f"{doc_type}.docx",
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True
        )
    
    except Exception as e:
        app.logger.error(f"Download error for {doc_type}: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))