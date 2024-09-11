import google.generativeai as genai
import time
import requests
import os
import json
import re
from urllib.parse import urlparse
from app import db  # Import Firestore client from app.py

# Configure your API key
genai.configure(api_key="AIzaSyDHieynF4wIDtQoogbBJmDZv2szFja8g5U")

def download_video_from_url(url, output_dir="downloads"):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    parsed_url = urlparse(url)
    video_filename = os.path.basename(parsed_url.path)
    video_path = os.path.join(output_dir, video_filename)
    
    response = requests.get(url, stream=True)
    
    if response.status_code == 200:
        with open(video_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return video_path
    else:
        return None

def upload_video_to_gemini(video_path, mime_type="video/mp4"):
    try:
        file = genai.upload_file(video_path, mime_type=mime_type)
        return file
    except Exception as e:
        print(f"Error during video upload: {e}")
        return None

def wait_for_file_processing(file, timeout=600):
    start_time = time.time()
    print("Processing video...")
    while True:
        try:
            file = genai.get_file(file.name)
            print(f"Current file state: {file.state.name}")
            
            if file.state.name == "ACTIVE":
                print("Video is ready for analysis.")
                break
            elif file.state.name == "FAILED":
                raise Exception("Video processing failed.")
            
            if time.time() - start_time > timeout:
                raise Exception("Timeout: Video processing took too long.")
            
            time.sleep(10)
        except Exception as e:
            print(f"Error during file processing: {e}")
            break

def analyze_video(file):
    try:
        system_instruction = """
        Role Definition:
        Instruction: "You are a content algorithm specialist focusing on analyzing video data. Your task is to extract every piece of information relevant to improving content recommendations, categorization, tagging, genre assignment, and other algorithm-driven tasks. The output should be structured in a way that is useful for content algorithms."

        Content Analysis:
        Instruction: "Analyze the video content fully, including audio, visual elements, transcripts, objects in scenes, actions, spoken words, and the emotional tone conveyed by characters. Use emotion analysis (without directly outputting emotions) to enhance the accuracy and depth of other categories like tagging, genre, sub-genre, and summary."

        Tagging and Categorization:
        Instruction: "For each video, generate as many detailed tags as possible based on detected objects, actions, spoken words, and themes. Assign multiple genres, sub-genres, and content categorization labels. Ensure that the output provides all possible relevant tags and categories, with the emotion analysis influencing how certain tags and categories are selected."

        Age Category Assignment:
        Instruction: "Based on the content, context, themes, and emotional tone, determine the most appropriate age category for the video. The possible categories are 'Toddler', 'Younger Kids', and 'Older Kids'. Ensure that the output contains only one age category that best fits the overall content of the video."

        Content Type Assignment:
        Instruction: "Determine the content type based on the visual style of the video. The possible categories are 'Live Action', '2D Animation', '3D Animation', and 'Stop Motion'. Ensure that the output contains only one content type that best describes the overall visual style of the video."

        Language Detection:
        Instruction: "Detect and specify the language(s) spoken in the video. Ensure the language is correctly identified based on the spoken words and transcript, and include it in the output. If there are multiple languages, list all that are detected."

        Action Detection:
        Instruction: "Analyze and detect all significant actions in the video. Provide a detailed list of these actions in the output, as they can influence the tags, categorization, and recommendations."

        Spoken Keyword Detection:
        Instruction: "Identify and extract key spoken words and phrases from the video’s dialogue and narration. These spoken keywords should be output as part of the final results and used to inform recommendations and categorizations."

        Title Detection:
        Instruction: "Search for any spoken mentions of the video title or visual indicators within the video that display the title (e.g., text on screen). If the title is mentioned or shown visually, capture and output it as part of the results."

        Recommendations:
        Instruction: "Utilize all extracted data, including the emotion, action, spoken keyword analysis, and title detection, to suggest how this video should be categorized in a recommendation system. Generate multiple keywords and tags that align with the visual content, emotional tone, actions, spoken words, and narrative in the video. Emotion analysis should subtly influence these recommendations and categorizations, while actions, spoken keywords, and title should be directly reported."

        Summary:
        Instruction: "Provide a detailed summary that explains the entire storyline of the video, incorporating key events, actions, spoken keywords, and themes. The emotion analysis should guide how the narrative and character motivations are described in the summary, ensuring that emotional shifts in the story are reflected without directly outputting emotions."

        Output Format:
        Instruction: "Output the results in JSON format, structured for direct integration into a content recommendation system. The data should include fields such as 'title', 'summary', 'language', 'age category', 'content type', 'genre', 'sub-genre', 'tags', 'keywords', and 'actions'. Ensure that only one content type and one age category are assigned, while other fields should include as much relevant data as possible."

        Multimodal Analysis:
        Instruction: "Consider all input types (audio, video frames, emotions, actions, spoken keywords, and text transcripts). Extract relevant data from each modality and combine it into a unified output that reflects the video's complete content. Include as much information as possible in the analysis, except for content type and age category, which should be limited to one.
        """

        model_config = {
            "temperature": 2,
            "max_output_tokens": 4096
        }

        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro-latest",
            system_instruction={"text": system_instruction},
            generation_config=model_config
        )
        
        response = model.generate_content(file)
        return response.text
    except Exception as e:
        return f"Error during video analysis: {e}"

def save_result_to_firebase(analysis_result, collection_id, video_id):
    """Save the analysis result and its embedding to Firebase."""
    try:
        # Remove extra symbols such as ```json and ```
        clean_result = re.sub(r"```json|```", "", analysis_result).strip()

        # Attempt to parse the cleaned result as JSON
        analysis_data = json.loads(clean_result)
        
        # Add the video_id to the parsed JSON data
        analysis_data['_id'] = video_id

        # Create an embedding for the text fields (e.g., summary)
        embedding_input = f"{analysis_data.get('summary', '')} {', '.join(analysis_data.get('tags', []))} {', '.join(analysis_data.get('keywords', []))}"
        
        # Generate embedding using Gemini API
        embedding_result = genai.embed_content(
            model="models/text-embedding-004",  # Use the appropriate model
            content=embedding_input,               # Concatenate relevant fields for embedding
            task_type="retrieval_document"
        )
        embedding_vector = embedding_result['embedding']
        
        # Add the embedding to the analysis data
        analysis_data['embedding'] = embedding_vector

        # Reference to the specific collection and video in Firestore
        doc_ref = db.collection('collections').document(collection_id).collection('videos').document(video_id)
        
        # Save the cleaned and structured JSON with embeddings to Firestore
        doc_ref.set(analysis_data)
        
        print(f"Analysis result and embedding saved to Firebase for video ID {video_id}")
    
    except json.JSONDecodeError as e:
        # Handle invalid JSON
        print(f"Failed to parse analysis result as JSON: {e}")
    
    except Exception as e:
        print(f"An error occurred: {e}")

def process_video(video_url, video_title, video_id, collection_id):
    video_path = download_video_from_url(video_url)
    
    if video_path:
        file = upload_video_to_gemini(video_path)
        if file:
            wait_for_file_processing(file)
            analysis_result = analyze_video(file)
            save_result_to_firebase(analysis_result, collection_id, video_id)
            return analysis_result
    return "Failed to process video."

