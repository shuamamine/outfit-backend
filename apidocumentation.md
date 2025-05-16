# Style Generator API Documentation

This API generates outfit recommendations and images based on input apparel images, using a consistent minimalist style template.

## Setup

1. Install dependencies:
```bash
pip install flask openai python-dotenv pillow
```

2. Create a `.env` file with your OpenAI API key:
```
OPENAI_API_KEY=your_api_key_here
```

3. Set up the reference template image:
   - The application expects a reference image at `public/assets/reference_style.jpg`
   - You can manually place the image there or use the `/upload-reference-template` endpoint

## Endpoints

### 1. Upload Reference Template

```
POST /upload-reference-template
```

Upload a new reference template image that defines the visual style for all generated outfit images.

**Request:**
- Form data with `template` (image file)

**Response:**
```json
{
  "success": "Reference template image uploaded successfully",
  "url": "/public/assets/reference_style.jpg"
}
```

### 2. Generate Style Recommendations and Images

```
POST /generate-styles
```

Analyze an input apparel image and generate three outfit recommendations with matching images.

**Request:**
- Form data with `image` (apparel image file)

**Response:**
```json
{
  "apparel": "yes",
  "details": ["list of apparel details"],
  "suggestions": {
    "party": "detailed party outfit description",
    "office": "detailed office outfit description",
    "vacation": "detailed vacation outfit description"
  },
  "generated_images": {
    "party": "dall-e-generated-image-url",
    "office": "dall-e-generated-image-url",
    "vacation": "dall-e-generated-image-url"
  }
}
```

### 3. Generate Single Outfit Image

```
POST /generate-single-outfit
```

Generate a single outfit image based on a custom description and input apparel.

**Request:**
- Form data with:
  - `image` (apparel image file)
  - `description` (text description of desired outfit)
  - `category` (optional: type of outfit, default is "custom")

**Response:**
```json
{
  "category": "party",
  "description": "outfit description",
  "image_url": "dall-e-generated-image-url"
}
```

### 4. Test Endpoint

```
GET /test
```

Simple test endpoint to verify the API is running.

## Implementation Details

The API uses:
- OpenAI's vision model (`gpt-4.1-nano`) to analyze apparel images and generate outfit recommendations
- OpenAI's DALL-E 3 model to generate outfit images in a consistent style
- A consistent reference template image to maintain visual style across all generated images
- A two-step process where the vision model provides style guidance before DALL-E generates the image

## Error Handling

All endpoints return appropriate error responses (400/500) with informative error messages when issues occur.