import os
from flask import Flask, render_template, request, jsonify, send_from_directory
import wave
import json
import subprocess
from werkzeug.utils import secure_filename
import re

app = Flask(__name__)

UPLOAD_FOLDER = 'wavs'
ALLOWED_EXTENSIONS = {'txt', 'wav'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit

TRANSCRIPTIONS = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def natural_sort_key(s):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

def read_transcriptions(file_path):
    transcriptions = {}
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            parts = line.strip().split('|')
            if len(parts) == 2:
                audio_id, text = parts
                audio_id = os.path.basename(audio_id)
                transcriptions[audio_id] = text
    return transcriptions  # Return transcriptions without sorting


@app.route('/')
def index():
    return render_template('index.html', transcriptions=TRANSCRIPTIONS)

@app.route('/sorted_files')
def sorted_files():
    files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if allowed_file(f)]
    return jsonify(files)  # Return files without sorting


@app.route('/upload_transcriptions', methods=['POST'])
def upload_transcriptions():
    global TRANSCRIPTIONS
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        try:
            TRANSCRIPTIONS = read_transcriptions(file_path)
            return jsonify({
                "status": "success",
                "message": "Transcriptions uploaded successfully",
                "transcriptions": TRANSCRIPTIONS,
                "filename": file.filename
            })
        except Exception as e:
            return jsonify({"status": "error", "message": f"Error processing file: {str(e)}"}), 500
    return jsonify({"status": "error", "message": "Invalid file type"}), 400


@app.route('/update_transcription', methods=['POST'])
def update_transcription():
    global TRANSCRIPTIONS
    data = request.json
    audio_id = data.get('audio_id')
    new_text = data.get('text')
    if audio_id and new_text:
        TRANSCRIPTIONS[audio_id] = new_text
        transcription_file = next((f for f in os.listdir(app.config['UPLOAD_FOLDER']) if f.endswith('.txt')), None)
        if transcription_file:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], transcription_file)
            with open(file_path, 'r', encoding='utf-8') as file:
                lines = file.readlines()
            
            with open(file_path, 'w', encoding='utf-8') as file:
                for line in lines:
                    parts = line.strip().split('|')
                    if len(parts) == 2:
                        line_audio_id, _ = parts
                        if line_audio_id == audio_id:
                            file.write(f"{audio_id}|{new_text}\n")
                        else:
                            file.write(line)
                    else:
                        file.write(line)
                
        return jsonify({"status": "success", "message": "Transcription updated successfully"})
    return jsonify({"status": "error", "message": "Invalid data"}), 400

@app.route('/record', methods=['POST'])
def record():
    if 'audio' not in request.files:
        return jsonify({"status": "error", "message": "No audio file provided"}), 400
    
    audio_id = request.form.get('audio_id')
    if not audio_id:
        return jsonify({"status": "error", "message": "No audio ID provided"}), 400

    audio_blob = request.files['audio']
    if audio_blob.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    if audio_blob and allowed_file(audio_blob.filename):
        filename = secure_filename(f"{audio_id}.wav")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        audio_blob.save(filepath)

        try:
            convert_audio(filepath)
            return jsonify({"status": "success", "message": f"Audio {audio_id} saved and converted successfully"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Error processing audio: {str(e)}"}), 500
    
    return jsonify({"status": "error", "message": "Invalid file type"}), 400

def convert_audio(filepath):
    output_filepath = filepath.replace('.wav', '_converted.wav')
    command = [
        'ffmpeg',
        '-i', filepath,
        '-acodec', 'pcm_s16le',
        '-ac', '1',
        '-ar', '22050',
        output_filepath
    ]
    subprocess.run(command, check=True)
    os.replace(output_filepath, filepath)

@app.route('/wavs/<path:filename>')
def serve_audio(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/list_files')
def list_files():
    files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if allowed_file(f)]
    return jsonify(sorted(files, key=natural_sort_key))

@app.route('/file_info/<path:filename>')
def file_info(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    file_stats = os.stat(filepath)
    if filename.endswith('.wav'):
        with wave.open(filepath, 'rb') as wf:
            params = wf.getparams()
            info = {
                "filename": filename,
                "size": file_stats.st_size,
                "created": file_stats.st_ctime,
                "modified": file_stats.st_mtime,
                "channels": params.nchannels,
                "sample_width": params.sampwidth,
                "framerate": params.framerate,
                "n_frames": params.nframes,
                "duration": params.nframes / params.framerate
            }
    else:
        info = {
            "filename": filename,
            "size": file_stats.st_size,
            "created": file_stats.st_ctime,
            "modified": file_stats.st_mtime
        }
    return jsonify(info)

@app.route('/set_upload_folder', methods=['POST'])
def set_upload_folder():
    data = request.json
    new_folder = data.get('folder')
    if new_folder:
        global UPLOAD_FOLDER
        UPLOAD_FOLDER = new_folder
        app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)
        return jsonify({"status": "success", "message": f"Upload folder set to {UPLOAD_FOLDER}"})
    return jsonify({"status": "error", "message": "Invalid folder path"}), 400

if __name__ == '__main__':
    app.run(debug=True)