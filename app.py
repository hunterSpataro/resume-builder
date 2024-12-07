from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import os
from dotenv import load_dotenv
import anthropic
import PyPDF2
import docx
from io import BytesIO

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

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
            
            Please provide:
            1. A tailored version of my resume. Important guidelines:
               - Start directly with my name and contact information, DO NOT add any introduction or title
               - Maintain strict accuracy - do not add or embellish any experiences that aren't in my original resume
               - Only reorganize and emphasize existing experiences that align with the job requirements
               - Keep all dates, titles, and company names exactly as they appear in the original
               - Use clear, professional formatting that is ATS-friendly
            
            2. A cover letter that balances professionalism with authenticity:
               - Maintain a consistently professional tone throughout
               - Show genuine interest in the role while avoiding overly casual language
               - Present a clear, logical connection between my experience and the role requirements
               - Use confident, direct language that demonstrates competence and reliability
               - Keep the opening and closing professional yet engaging
               - Focus on concrete achievements and specific qualifications
            
            Please start the cover letter section with exactly "COVER LETTER:" on its own line."""

            message = self.client.messages.create(
                model="claude-3-opus-20240229",
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
            print(f"Error in generate_documents: {str(e)}")
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
            
        # Store generated documents in app config for download
        app.config['GENERATED_RESUME'] = result['resume']
        app.config['GENERATED_COVER'] = result['cover_letter']
        
        return jsonify({'success': True, 'message': 'Documents generated successfully'})
        
    except Exception as e:
        app.logger.error(f"Unexpected error in /generate endpoint: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred. Please try again.'}), 500

@app.route('/download/<doc_type>/docx', methods=['GET'])
def download(doc_type):
    try:
        if doc_type not in ['resume', 'cover']:
            return jsonify({'error': 'Invalid document type'}), 400
        
        content = app.config.get(f'GENERATED_{doc_type.upper()}', '')
        if not content:
            return jsonify({'error': 'No generated content found'}), 404
        
        # Create DOCX and serve
        doc = create_docx(content)
        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            download_name=f"{doc_type}.docx",
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True
        )
    
    except Exception as e:
        print(f"Download error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("\n=== Starting Resume Builder Server ===")
    print("Server will run at: http://127.0.0.1:5000")
    print("Make sure you have:")
    print("1. Set your CLAUDE_API_KEY in .env file")
    print("2. Installed all required packages")
    print("=====================================\n")
    app.run(host='127.0.0.1', port=5000, debug=True)