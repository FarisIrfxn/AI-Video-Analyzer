from flask import Flask, render_template, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import gemini  # Import gemini.py as a module
import requests

# Check if the default app is already initialized
if not firebase_admin._apps:
    cred = credentials.Certificate('')
    firebase_app = firebase_admin.initialize_app(cred)
else:
    firebase_app = firebase_admin.get_app()

# Initialize Firestore client
db = firestore.client()

# Initialize Flask app
app = Flask(__name__)

def load_processed_videos():
    """Load the processed videos from Firestore."""
    processed_videos_ref = db.collection('processed_videos')
    docs = processed_videos_ref.stream()
    processed_videos = {}

    for doc in docs:
        processed_videos[doc.id] = doc.to_dict().get('videos', [])

    return processed_videos

def save_processed_video(collection_id, video_id):
    """Save a processed video record to Firestore."""
    processed_videos_ref = db.collection('processed_videos').document(collection_id)
    doc = processed_videos_ref.get()

    if doc.exists:
        processed_videos_ref.update({
            'videos': firestore.ArrayUnion([video_id])
        })
    else:
        processed_videos_ref.set({
            'videos': [video_id]
        })

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_collections', methods=['GET'])
def get_collections():
    api_url = "https://test.com/collections"
    headers = {
        "Authorization": "Bearer"
    }

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        collections_data = response.json()

        if 'data' in collections_data:
            collections = collections_data['data']

            processed_videos = load_processed_videos()
            for collection in collections:
                collection_id = collection['_id']
                total_videos = collection.get('num_of_videos', 0)
                processed_count = len(processed_videos.get(collection_id, []))

                collection['video_count'] = total_videos
                collection['processed_count'] = processed_count

            return jsonify(collections)
        else:
            return jsonify({'result': 'No collections found.'}), 404

    except Exception as e:
        return jsonify({'result': f"Error fetching collections: {e}"}), 500

@app.route('/load_videos', methods=['POST'])
def load_videos():
    global video_data
    data = request.get_json()
    if '_id' not in data:
        return jsonify({'result': 'No Collection ID provided.'}), 400

    collection_id = data['_id']
    api_url = f"https://test.com/collections/{collection_id}/videos"
    
    headers = {
        "Authorization": "Bearer"
    }

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        video_data = response.json()
        
        if 'data' in video_data:
            video_data = video_data['data']
            
            processed_videos = load_processed_videos()
            processed_video_ids = processed_videos.get(collection_id, [])

            for video in video_data:
                video_id = video['_id']
                video['is_processed'] = video_id in processed_video_ids

        return jsonify(video_data)
    except Exception as e:
        return jsonify({'result': f"Error fetching videos: {e}"}), 500

@app.route('/get_processed_videos', methods=['GET'])
def get_processed_videos():
    """Endpoint to fetch the list of processed videos."""
    return jsonify(load_processed_videos())

@app.route('/process_selected_videos', methods=['POST'])
def process_selected_videos():
    data = request.get_json()
    if 'video_urls' not in data or not data['video_urls']:
        return jsonify({'result': 'No video URLs provided.'}), 400

    processed_videos = []
    
    for video_url in data['video_urls']:
        try:
            video = next(video for video in video_data if video['videos']['transcoded'].get('sd') == video_url)
        except StopIteration:
            return jsonify({'result': 'Video URL not found in the provided data.'}), 400

        video_title = video['videos']['title']
        thumbnail = video['videos'].get('image_thumbnail', '/static/assets/default-thumbnail.png')
        video_id = video['_id']
        collection_id = video.get('collection_id')

        # Call the function from gemini.py to process the video and save the result
        result = gemini.process_video(video_url, video_title, video_id, collection_id)
        
        status = "Done" if result != "Failed to process video." else "Failed"

        if status == "Done":
            save_processed_video(collection_id, video_id)

        processed_videos.append({
            'video_url': video_url,
            'thumbnail': thumbnail,
            'title': video_title,
            'status': status
        })

    return jsonify({'processed_videos': processed_videos})

if __name__ == "__main__":
    app.run(debug=True)
