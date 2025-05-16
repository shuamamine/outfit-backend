import os
import shutil
import uuid
import datetime
import json
from flask import Flask, request, jsonify, send_from_directory, session
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image
import io
import base64
import requests
from flask_cors import CORS
import sqlite3

load_dotenv()
# Create the OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev_secret_key")  # For session management
CORS(app)
# Create necessary directories if they don't exist
os.makedirs("public/assets", exist_ok=True)
os.makedirs("public/history", exist_ok=True)

# Save reference style image if it doesn't exist
REFERENCE_IMAGE_PATH = "public/assets/reference_style.jpg"
if not os.path.exists(REFERENCE_IMAGE_PATH):
    # You'll need to save the reference image manually or from a URL
    # For now, we'll assume this step is done manually
    pass


def get_db_connection():
    """Create a connection to the SQLite database"""
    db_path = os.path.join(os.path.dirname(__file__), 'fashion_stylist.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # This enables column access by name
    return conn

# Call at startup
def initialize_db():
    """Create the necessary tables if they don't exist"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create sessions table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE,
        timestamp TEXT,
        created_at INTEGER,
        type TEXT,
        input_image_path TEXT,
        preview_image TEXT
    )
    ''')
    
    # Create generated_images table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS generated_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        occasion TEXT,
        image_path TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions (session_id)
    )
    ''')
    
    # Create style_data table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS style_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        apparel TEXT,
        details TEXT,  
        suggestion_party TEXT,
        suggestion_office TEXT,
        suggestion_vacation TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions (session_id)
    )
    ''')
    
    conn.commit()
    conn.close()

# Helper to convert image to base64
def image_to_base64(image_file):
    """Convert an image file to base64 encoding"""
    img_data = image_file.read()
    return base64.b64encode(img_data).decode('utf-8')

# Helper to save base64 image to file
def save_base64_image(base64_string, filepath):
    img_data = base64.b64decode(base64_string)
    with open(filepath, 'wb') as f:
        f.write(img_data)
    return filepath

# Helper to save image from file storage
def save_image_file(image_file, filepath):
    """Save an image file to the specified path"""
    image_file.save(filepath)
    return filepath

# Generate a unique session ID if not exists
def get_session_id():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']

# Create a folder for the current session
def get_session_folder():
    """Create and return the session folder path"""
    base_folder = os.path.join(os.path.dirname(__file__), 'public', 'history')
    os.makedirs(base_folder, exist_ok=True)
    return base_folder

# Save history data to JSON file
def save_history_data(data):
    session_folder = get_session_folder()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save metadata
    metadata_path = os.path.join(session_folder, f"metadata_{timestamp}.json")
    with open(metadata_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    # Update session index file
    index_path = os.path.join(session_folder, "index.json")
    if os.path.exists(index_path):
        with open(index_path, 'r') as f:
            index_data = json.load(f)
    else:
        index_data = {"history": []}
    
    # Add new entry to index
    entry = {
        "timestamp": timestamp,
        "metadata_file": f"metadata_{timestamp}.json",
        "input_image": data.get("input_image_path", ""),
        "type": data.get("type", "generate-styles"),
        "preview": data.get("preview_image", "")
    }
    
    index_data["history"].append(entry)
    
    with open(index_path, 'w') as f:
        json.dump(index_data, f, indent=2)
    
    return metadata_path

def save_history_data_sqlite(data):
    """Save history data to SQLite database instead of JSON files"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"session-{int(datetime.datetime.now().timestamp() * 1000)}"
    created_at = int(datetime.datetime.now().timestamp() * 1000)
    
    # Insert into sessions table
    cursor.execute('''
    INSERT INTO sessions (session_id, timestamp, created_at, type, input_image_path, preview_image)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        session_id,
        timestamp,
        created_at,
        data.get('type', 'generate-styles'),
        data.get('input_image_path', ''),
        data.get('preview_image', '')
    ))
    
    # Insert style data
    style_data = data.get('style_data', {})
    cursor.execute('''
    INSERT INTO style_data (session_id, apparel, details, suggestion_party, suggestion_office, suggestion_vacation)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        session_id,
        style_data.get('apparel', 'no'),
        json.dumps(style_data.get('details', [])),
        style_data.get('suggestions', {}).get('party', ''),
        style_data.get('suggestions', {}).get('office', ''),
        style_data.get('suggestions', {}).get('vacation', '')
    ))
    
    # Insert generated images
    for occasion, image_path in data.get('output_images', {}).items():
        cursor.execute('''
        INSERT INTO generated_images (session_id, occasion, image_path)
        VALUES (?, ?, ?)
        ''', (session_id, occasion, image_path))
    
    conn.commit()
    conn.close()
    
    return session_id
@app.route('/test', methods=['GET'])
def test():
    return "Niggu"

@app.route('/generate-styles', methods=['POST'])
def generate_styles():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400

    image_file = request.files['image']
    base64_img = image_to_base64(image_file)

    # Save the input image to history folder
    session_folder = get_session_folder()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    input_image_path = os.path.join(session_folder, f"input_{timestamp}.jpg")
    image_file.seek(0)  # Reset file pointer after reading for base64
    save_image_file(image_file, input_image_path)
    
    # Relative path for storage in JSON
    rel_input_path = os.path.relpath(input_image_path, "public")

    prompt = """
You are a fashion stylist AI. Analyze the image and return the following JSON:
{
  "apparel": "yes" or "no" based on whether the image contains any apparel,
  "details": [list of visual and stylistic details about the apparel very intricate and minute],
  "suggestions": {
    "party": "describe a complete party outfit including accessories, shoes, etc. using the given apparel,very intricate and minute",
    "office": "describe a complete office outfit with accessories and shoes using the given apparel very intricate and minute",
    "vacation": "describe a vacation-appropriate outfit in detail using the given apparel very intricate and minute"
  }
}
Ensure the output is valid JSON only.
Also, try to identify whether given apparel is male/female/unisex, accordingly draft the suggestions 
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": "You are a helpful fashion stylist AI."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_img}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=4096
        )

        raw_content = response.choices[0].message.content.strip()
        style_data = json.loads(raw_content)
        
        # Generate outfit images based on recommendations
        outfit_images, local_image_paths = generate_outfit_images(style_data, base64_img, session_folder, timestamp)
        
        # Add image URLs to the response
        style_data["generated_images"] = outfit_images
        
        # Save history data
        history_data = {
            "type": "generate-styles",
            "timestamp": timestamp,
            "input_image_path": rel_input_path,
            "style_data": style_data,
            "output_images": local_image_paths,
            "preview_image": local_image_paths.get("party", "")  # Use party image as preview
        }
        save_history_data_sqlite(history_data)
        
        return jsonify(style_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def get_reference_style_base64():
    """Get the reference style image as base64"""
    with open(REFERENCE_IMAGE_PATH, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def generate_outfit_images(style_data, input_image_base64, session_folder, timestamp):
    """Generate outfit images using DALL-E 3 based on style recommendations"""
    outfit_images = {}
    local_image_paths = {}
    
    # Use the saved reference style image
    try:
        reference_image_base64 = get_reference_style_base64()
    except Exception as e:
        # If reference image isn't available, use a default approach
        reference_image_base64 = input_image_base64
    
    # Categories to generate images for
    categories = ["party", "office", "vacation"]
    details = ", ".join(style_data["details"])
    for category in categories:
        description = style_data["suggestions"][category]
        
        # Create prompt for DALL-E that includes reference to template style
        prompt = f"""Create a fashion photo in the exact same minimalist, clean style as the reference template image.
Show a complete {category} outfit as described:
{description}. Display outfit items floating (invisible mannequin) in centered composition

Follow these STRICT guidelines:
1. Use a plain beige/off-white background
3. Use bright, even lighting with soft shadows
4. Include all mentioned accessories arranged as in the reference
5. Keep the exact same minimalist aesthetic and clean composition as reference
6. Use similar professional product photography style
7. Do not include any text, logos, or watermarks
8. The outfit must contain the given input image, the details of that image are : {details}
"""
        
        try:
            # First provide both reference template image and input image for context
            context_response = client.chat.completions.create(
                model="gpt-4.1-nano",
                messages=[
                    {"role": "system", "content": "You are a fashion stylist AI specialized in product photography styling."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "This is the REFERENCE TEMPLATE IMAGE style I want all generated outfits to match exactly:"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{reference_image_base64}"
                                }
                            }
                        ]
                    },
                    {"role": "assistant", "content": "I understand the reference template style. I'll ensure all generated outfits match this exact minimalist aesthetic with floating garments on a neutral background."},
                    {
                        "role": "user", 
                        "content": [
                            {"type": "text", "text": "This is the INPUT APPAREL image we're creating recommendations for:"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{input_image_base64}"
                                }
                            }
                        ]
                    },
                    {"role": "assistant", "content": "I see the input apparel. What kind of outfit would you like me to create with it?"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2048
            )
            
            # Get style guidance from the vision model
            style_guidance = context_response.choices[0].message.content
            
            # Enhanced prompt with style guidance
            enhanced_prompt = f"{prompt}\n\nAdditional style guidance: {style_guidance}"
            
            # Generate the image with DALL-E 3
            image_response = client.images.generate(
                model="dall-e-3",
                prompt=enhanced_prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            
            # Get the image URL from DALL-E response
            image_url = image_response.data[0].url
            
            # Download the image and save it locally
            import requests
            response = requests.get(image_url)
            if response.status_code == 200:
                local_image_path = os.path.join(session_folder, f"output_{category}_{timestamp}.jpg")
                with open(local_image_path, 'wb') as f:
                    f.write(response.content)
                
                # Store both the external URL and local path
                outfit_images[category] = image_url
                local_image_paths[category] = os.path.relpath(local_image_path, "public")
            else:
                outfit_images[category] = "Error downloading image"
                local_image_paths[category] = ""
            
        except Exception as e:
            outfit_images[category] = f"Error generating image: {str(e)}"
            local_image_paths[category] = ""
    
    return outfit_images, local_image_paths

@app.route('/history/<path:filename>')
def serve_public(filename):
    """Serve files from the public directory"""
    return send_from_directory('public/history', filename)

@app.route('/upload-reference-template', methods=['POST'])
def upload_reference_template():
    """Upload a new reference template image"""
    if 'template' not in request.files:
        return jsonify({'error': 'No template image uploaded'}), 400
        
    template_file = request.files['template']
    
    try:
        # Save the template image to the assets folder
        template_file.save(REFERENCE_IMAGE_PATH)
        return jsonify({'success': 'Reference template image uploaded successfully', 
                      'url': f'/public/assets/reference_style.jpg'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/generate-single-outfit', methods=['POST'])
def generate_single_outfit():
    """Generate a single outfit image based on description and input apparel image"""
    if 'image' not in request.files:
        return jsonify({'error': 'No input apparel image uploaded'}), 400
    
    if 'description' not in request.form:
        return jsonify({'error': 'No outfit description provided'}), 400
        
    input_image_file = request.files['image']
    input_base64_img = image_to_base64(input_image_file)
    description = request.form['description']
    category = request.form.get('category', 'custom')
    
    # Save the input image to history folder
    session_folder = get_session_folder()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    input_image_path = os.path.join(session_folder, f"input_{timestamp}.jpg")
    input_image_file.seek(0)  # Reset file pointer after reading for base64
    save_image_file(input_image_file, input_image_path)
    
    # Relative path for storage in JSON
    rel_input_path = os.path.relpath(input_image_path, "public")
    
    try:
        # Get reference template image
        reference_image_base64 = get_reference_style_base64()
        
        # Create prompt for DALL-E that references the template style
        prompt = f"""Create a fashion photo in the exact same minimalist, clean style as the reference template image.
Show a complete {category} outfit as described:
{description}

Follow these STRICT guidelines:
1. Use a plain beige/off-white background
2. Display outfit items floating (invisible mannequin) in centered composition
3. Use bright, even lighting with soft shadows
4. Include all mentioned accessories arranged as in the reference
5. Keep the exact same minimalist aesthetic and clean composition as reference
6. Use similar professional product photography style
7. Do not include any text, logos, or watermarks
"""
        
        # First provide both reference template image and input image for context
        context_response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": "You are a fashion stylist AI specialized in product photography styling."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "This is the REFERENCE TEMPLATE IMAGE style I want the outfit to match exactly:"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{reference_image_base64}"
                            }
                        }
                    ]
                },
                {"role": "assistant", "content": "I understand the reference template style. I'll ensure the generated outfit matches this exact minimalist aesthetic."},
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": "This is the INPUT APPAREL image we're creating a recommendation for:"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{input_base64_img}"
                            }
                        }
                    ]
                },
                {"role": "assistant", "content": "I see the input apparel. What kind of outfit would you like me to create with it?"},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150
        )
        
        # Get style guidance from the vision model
        style_guidance = context_response.choices[0].message.content
        
        # Enhanced prompt with style guidance
        enhanced_prompt = f"{prompt}\n\nAdditional style guidance: {style_guidance}"
        
        # Generate the image with DALL-E 3
        image_response = client.images.generate(
            model="dall-e-3",
            prompt=enhanced_prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        
        # Get the image URL
        image_url = image_response.data[0].url
        
        # Download and save the output image
        
        response = requests.get(image_url)
        local_output_path = ""
        rel_output_path = ""
        
        if response.status_code == 200:
            local_output_path = os.path.join(session_folder, f"output_{category}_{timestamp}.jpg")
            with open(local_output_path, 'wb') as f:
                f.write(response.content)
            rel_output_path = os.path.relpath(local_output_path, "public")
        print(rel_output_path)
        # Save history data
        history_data = {
            "type": "single-outfit",
            "timestamp": timestamp,
            "input_image_path": rel_input_path,
            "output_image_path": rel_output_path,
            "category": category,
            "description": description,
            "preview_image": rel_output_path
        }
        save_history_data(history_data)
        
        # Return the image URL and local path
        return jsonify({
            "category": category,
            "description": description,
            "image_url": image_url,
            "local_image_path": rel_output_path if rel_output_path else ""
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def get_history():
    """Retrieve history data from SQLite database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all sessions ordered by created_at in descending order
    cursor.execute('''
    SELECT * FROM sessions ORDER BY created_at DESC
    ''')
    
    sessions = cursor.fetchall()
    history = []
    
    for session in sessions:
        session_id = session['session_id']
        
        # Get style data for this session
        cursor.execute('SELECT * FROM style_data WHERE session_id = ?', (session_id,))
        style_data_row = cursor.fetchone()
        
        # Get generated images for this session
        cursor.execute('SELECT occasion, image_path FROM generated_images WHERE session_id = ?', (session_id,))
        images = cursor.fetchall()
        
        # Create history item in format matching frontend expectations
        history_item = {
            'sessionId': session_id,
            'uploaded': f"/history/{os.path.basename(session['input_image_path'])}",
            'results': [
                {
                    'url': f"/history/{os.path.basename(img['image_path'])}",
                    'occasion': img['occasion'].capitalize()
                } for img in images
            ],
            'createdAt': session['created_at']
        }
        
        history.append(history_item)
    
    conn.close()
    return history

@app.route('/history/detail/<timestamp>', methods=['GET'])
def get_history_detail(timestamp):
    """Get detailed information about a specific history entry"""
    try:
        session_folder = get_session_folder()
        metadata_path = os.path.join(session_folder, f"metadata_{timestamp}.json")
        
        if not os.path.exists(metadata_path):
            return jsonify({"error": "History entry not found"}), 404
            
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
            
        # Add URLs for frontend access
        if "input_image_path" in metadata and metadata["input_image_path"]:
            metadata["input_image_url"] = f"/public/{metadata['input_image_path']}"
            
        if "output_image_path" in metadata and metadata["output_image_path"]:
            metadata["output_image_url"] = f"/public/{metadata['output_image_path']}"
        
        if "output_images" in metadata:
            for category, path in metadata["output_images"].items():
                if path:
                    if "output_image_urls" not in metadata:
                        metadata["output_image_urls"] = {}
                    metadata["output_image_urls"][category] = f"/public/{path}"
                    
        return jsonify(metadata)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/clear-history', methods=['POST'])
def clear_history():
    """Clear history for the current session"""
    try:
        session_folder = get_session_folder()
        
        # Delete all files in the session folder
        if os.path.exists(session_folder):
            shutil.rmtree(session_folder)
            os.makedirs(session_folder, exist_ok=True)
            
        return jsonify({"success": "History cleared successfully"})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/generate-styles2', methods=['POST'])
def generate_styles2():
    dummy_response = {
        "apparel": "yes",
        "details": [
            "Ribbed texture with vertical lines running throughout the fabric, providing a structured and slightly stretchy feel.",
            "Short-sleeved design with a fitted cut, suitable for warm weather.",
            "Collar features a classic, pointed design with a slight spread, adding a touch of formality.",
            "Placket with a concealed button closure, maintaining a sleek appearance.",
            "Brown color with subtle shading variations that enhances depth and richness.",
            "Seams are well-stitched, with slight topstitching visible along the edges of the collar and sleeve hems.",
            "Slim fit silhouette tailored to accentuate the waist area.",
            "Made from a lightweight, breathable fabric, likely a cotton or cotton blend."
        ],
        "generated_images": {
            "office": "https://oaidalleapiprodscus.blob.core.windows.net/private/org-dIA4g1qKxWkQ5OItkKvoUDns/user-XFro1h9ZJ3YtmiznsZ2TW368/img-4rBIeLbyqfy80u9mcyXYGTgm.png?st=2025-05-15T17%3A27%3A29Z&se=2025-05-15T19%3A27%3A29Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=475fd488-6c59-44a5-9aa9-31c4db451bea&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2025-05-14T20%3A56%3A53Z&ske=2025-05-15T20%3A56%3A53Z&sks=b&skv=2024-08-04&sig=d6raV01fC7Gl8NQZfDnzD77CJKN8zCHq71eGZPxDqaw%3D",
            "party": "https://oaidalleapiprodscus.blob.core.windows.net/private/org-dIA4g1qKxWkQ5OItkKvoUDns/user-XFro1h9ZJ3YtmiznsZ2TW368/img-A9m4ov9jIebffKYeHBNevUxY.png?st=2025-05-15T17%3A26%3A54Z&se=2025-05-15T19%3A26%3A54Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=475fd488-6c59-44a5-9aa9-31c4db451bea&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2025-05-14T21%3A03%3A36Z&ske=2025-05-15T21%3A03%3A36Z&sks=b&skv=2024-08-04&sig=YaS18An3%2BeXe3nLxTaak1OLW2Cl719eolnp3H5GlarI%3D",
            "vacation": "https://oaidalleapiprodscus.blob.core.windows.net/private/org-dIA4g1qKxWkQ5OItkKvoUDns/user-XFro1h9ZJ3YtmiznsZ2TW368/img-PB3oLy6vtzoodOyJSxtpHkw1.png?st=2025-05-15T17%3A27%3A52Z&se=2025-05-15T19%3A27%3A52Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=475fd488-6c59-44a5-9aa9-31c4db451bea&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2025-05-14T21%3A39%3A23Z&ske=2025-05-15T21%3A39%3A23Z&sks=b&skv=2024-08-04&sig=TQZeDXsFdL4JKYWrAMveD8IWZdXTD4iAE5dYKV1g%2B8E%3D"
        },
        "suggestions": {
            "office": "Combine the brown ribbed shirt with tailored beige or charcoal gray high-waisted trousers, ensuring a clean and professional appearance. Tuck in the shirt neatly and add a slim brown leather belt with a subtle gold buckle. Accessorize with small gold or pearl stud earrings, a classic wristwatch, and a structured leather handbag in dark brown. Wear pointed-toe loafers or low-heeled pumps in brown or nude. Style your hair in a sleek bun or softly curled, and opt for natural makeup with a nude lipstick for a polished, work-appropriate look.",
            "party": "Pair the brown ribbed short-sleeved shirt with a high-waisted black or dark denim skirt adorned with metallic embellishments like studs or glitter details. Add statement jewelry such as gold chandelier earrings, layered necklaces, and a bold cuff bracelet. Complete the look with strappy stiletto heels in a metallic or matching brown shade, and a small clutch in a contrasting color like beige or gold. Finish with a smoky eye makeup and a nude or deep red lipstick for a glamorous evening appearance.",
            "vacation": "Dress the brown ribbed shirt with a flowy, knee-length beige linen skirt featuring subtle pleats for comfort and style. Accessorize with a wide-brim straw hat, oversized sunglasses, and layered beaded necklaces for a relaxed vibe. Carry a woven straw tote bag and wear comfortable tan leather sandals or espadrilles. Keep makeup minimal with a tinted moisturizer, and add a pop of color with coral or peach-colored lips and cheeks. Style hair in loose beachy waves for an effortless vacation look."
        }
    }

   
    return jsonify(dummy_response)
@app.route('/history', methods=['GET'])
def get_history_endpoint():
    """Endpoint to retrieve session history"""
    try:
        history = get_history()
        return jsonify(history)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/delete-session/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    """Delete a session and all associated data including files"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get file paths that need to be deleted
        # Get input image path
        cursor.execute('SELECT input_image_path, preview_image FROM sessions WHERE session_id = ?', (session_id,))
        session_data = cursor.fetchone()
        if not session_data:
            conn.close()
            return jsonify({'error': 'Session not found'}), 404
            
        files_to_delete = []
        
        # Add input image to deletion list
        if session_data['input_image_path']:
            input_path = os.path.join('public', session_data['input_image_path'])
            files_to_delete.append(input_path)
        
        # Get all generated image paths
        cursor.execute('SELECT image_path FROM generated_images WHERE session_id = ?', (session_id,))
        image_paths = cursor.fetchall()
        
        for image in image_paths:
            if image['image_path']:
                image_path = os.path.join('public', image['image_path'])
                files_to_delete.append(image_path)
        
        # Delete database records first (due to foreign key constraints)
        # Delete generated_images records
        cursor.execute('DELETE FROM generated_images WHERE session_id = ?', (session_id,))
        
        # Delete style_data records
        cursor.execute('DELETE FROM style_data WHERE session_id = ?', (session_id,))
        
        # Delete session record
        cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
        
        # Commit database changes
        conn.commit()
        conn.close()
        
        # Delete files from filesystem
        for file_path in files_to_delete:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as file_error:
                # Log the error but continue with other files
                print(f"Error deleting file {file_path}: {file_error}")
        
        return jsonify({'success': True, 'message': f'Session {session_id} and all associated data deleted successfully'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
initialize_db()
if __name__ == '__main__':
    app.run(debug=True, port=5000)