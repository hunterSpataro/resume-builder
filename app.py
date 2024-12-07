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
            
            Please provide:
            1. A tailored version of my resume (begin directly with the content):

            Format & Structure:
               - Begin directly with my name and contact details (no title or introduction)
               - Use clear, ATS-friendly formatting
               - Maintain all original dates, company names, and job titles exactly as shown

            Professional Summary (max 3-4 lines):
               - Craft a compelling narrative that showcases my most relevant experiences for this role
               - Focus on demonstrating the direct connection between my background and the job requirements
               - Emphasize unique value propositions that set me apart for this specific position
               - Keep the tone professional yet conversational

            Experience Section:
               - Reframe existing accomplishments to highlight skills and experiences most relevant to this role
               - Prioritize achievements that directly align with the job requirements
               - Maintain complete accuracy - no fabricated or enhanced experiences
               - When rewording, focus on emphasizing transferable skills and relevant outcomes
               - Use strong action verbs that align with the job description's key requirements

            Additional Guidelines:
               - Only use information present in my original resume
               - Reorganize content to put the most relevant experiences first
               - Ensure all claims are verifiable and based on my actual experience
            
            2. A cover letter that demonstrates genuine enthusiasm while maintaining professional polish:

            Format & Structure:
               - Include complete header with:
                  * My full name
                  * Company name and address
                  * Date
                  * Hiring manager's name/title (if provided)
                  * My contact information
               - Use standard business letter formatting
               - Length: Approximately 220 words for the main content

            Opening Paragraph:
               - Begin with a warm yet professional greeting
               - Introduce yourself and state the position of interest
               - Include a compelling hook that shows genuine interest in the role and company
               - Avoid generic openings or stating obvious information about the position

            Body Paragraphs:
               - Create a natural flow between your experience and the role requirements
               - Highlight 2-3 specific achievements that directly relate to the position
               - Demonstrate clear understanding of the company's needs and how you can address them
               - Use storytelling elements to make your experience more engaging
               - Balance confidence with humility
               - Support claims with concrete examples and measurable results

            Closing:
               - Express genuine interest in discussing the opportunity further
               - Include a clear call to action
               - End with a professional but warm closing
               - Maintain an optimistic and forward-looking tone

            Style Guidelines:
               - Write in a natural, conversational tone while maintaining professionalism
               - Avoid clichés and generic phrases
               - Use active voice and strong action verbs
               - Ensure each paragraph flows smoothly into the next
               - Strike a balance between expertise and approachability
               - Show personality while remaining business-appropriate
               - Demonstrate enthusiasm without appearing desperate
            
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
        app.logger.info(f"Download requested for {doc_type}")
        
        if doc_type not in ['resume', 'cover']:
            app.logger.error(f"Invalid document type requested: {doc_type}")
            return jsonify({'error': 'Invalid document type'}), 400
        
        content = app.config.get(f'GENERATED_{doc_type.upper()}')
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
    # Timeout set to 120 seconds
    from werkzeug.serving import run_simple
    run_simple('127.0.0.1', 5000, app, threaded=True, use_reloader=True)