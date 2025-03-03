import os
import subprocess
import uuid
import glob
from flask import Flask, render_template_string, request, send_file, after_this_request
import argparse

# Default acceleration and extra encoding options
accel = 'auto'
extra = '-crf 63 -c:v libx264'  # default extra settings

# Argument parser for command-line options
parser = argparse.ArgumentParser(description="Decodes using Android GPU, Encodes on CPU with H.264.")
parser.add_argument("--android", action="store_true", help="Enable Mediacodec decoding.")
parser.add_argument("--cuda", action="store_true", help="Enable encoding with Nvidia.")
parser.add_argument("--cudacpu", action="store_true", help="Enable decoding using the Nvidia CPU, but encodes on the CPU.")
parser.add_argument("--home", action="store_true", help="Use the system home directory for uploads and converted files.")
args = parser.parse_args()

if args.android:
    accel = 'mediacodec'
    extra = '-crf 63 -c:v libx264'
elif args.cudacpu:
    accel = 'cuda'
    extra = '-crf 63 -c:v libx264'
elif args.cuda:
    accel = 'auto'
    extra = '-b:v 1k -c:v h264_nvenc'

# Determine the directories based on the --home flag.
if args.home:
    home_dir = os.path.expanduser("~")
    UPLOAD_FOLDER = os.path.join(home_dir, 'uploads')
    CONVERTED_FOLDER = os.path.join(home_dir, 'converted')
else:
    UPLOAD_FOLDER = 'uploads'
    CONVERTED_FOLDER = 'converted'

# Helper function to configure audio options
def configure_audio(cmd_list, use_mp3):
    if use_mp3:
        cmd_list.extend(['-c:a', 'libmp3lame', '-b:a', '8k', '-ar', '24k', '-ac', '1'])
    else:
        cmd_list.extend(['-c:a', 'aac', '-b:a', '1k', '-ar', '8k', '-ac', '1'])

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['CONVERTED_FOLDER'] = CONVERTED_FOLDER

# Ensure upload and converted directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['CONVERTED_FOLDER'], exist_ok=True)

# Embedded HTML template with Dark Mode support, YouTube URL toggle, and audio-only option.
html_template = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Low quality Video inator</title>
  <style>
    body {
      background-color: #f5f5f5;
      color: #333;
      font-family: Arial, sans-serif;
      transition: background-color 0.3s, color 0.3s;
    }
    body.dark-mode {
      background-color: #333;
      color: #f5f5f5;
    }
    .container {
      width: 80%;
      max-width: 600px;
      margin: 50px auto;
      padding: 20px;
      box-shadow: 0 0 10px rgba(0,0,0,0.1);
      background: #fff;
    }
    body.dark-mode .container {
      background: #444;
    }
    .toggle-dark {
      float: right;
      margin-top: -10px;
      padding: 5px 10px;
      cursor: pointer;
      background-color: #007BFF;
      border: none;
      color: white;
      border-radius: 3px;
    }
    label {
      display: block;
      margin-top: 15px;
    }
    #file-input-container, #youtube-url-container {
      margin-top: 5px;
    }
    input[type="file"],
    input[type="text"] {
      width: 100%;
      padding: 5px;
      margin-top: 5px;
    }
    input[type="submit"] {
      margin-top: 20px;
      padding: 10px 20px;
      background-color: #28a745;
      border: none;
      color: white;
      border-radius: 3px;
      cursor: pointer;
    }
  </style>
</head>
<body>
  <div class="container">
    <button class="toggle-dark" onclick="toggleDarkMode()">Toggle Dark Mode</button>
    <h1>Video Converter</h1>
    <form method="post" enctype="multipart/form-data">
      <!-- YouTube Option -->
      <label>
        <input type="checkbox" name="youtube" id="youtube" onchange="toggleYoutube()">
        Use YouTube URL
      </label>
      <div id="youtube-url-container" style="display: none;">
        <label for="youtube_url">YouTube URL:</label>
        <input type="text" name="youtube_url" id="youtube_url">
      </div>
      
      <!-- File Upload Option -->
      <div id="file-input-container">
        <label for="video">Upload Video:</label>
        <input type="file" name="video" id="video" required>
      </div>

      <!-- Other Options -->
      <label>
        <input type="checkbox" name="downscale" id="downscale">
        Downscale Video (144p)
      </label>

      <label>
        <input type="checkbox" name="faster" id="faster">
        Faster Conversion (more pixelated)
      </label>

      <label>
        <input type="checkbox" name="use_mp3" id="use_mp3">
        Use MP3 (the video audio compression)
      </label>

      <label>
        <input type="checkbox" name="audio" id="audio">
        Only Audio (no video)
      </label>

      <input type="submit" value="Convert Video">
    </form>
  </div>
  <script>
    function toggleDarkMode() {
      document.body.classList.toggle('dark-mode');
    }
    
    function toggleYoutube() {
      var ytCheckbox = document.getElementById("youtube");
      var youtubeContainer = document.getElementById("youtube-url-container");
      var fileContainer = document.getElementById("file-input-container");
      var fileInput = document.getElementById("video");

      if (ytCheckbox.checked) {
        // Show YouTube URL input, hide file chooser, and remove file requirement
        youtubeContainer.style.display = "block";
        fileContainer.style.display = "none";
        fileInput.required = false;
      } else {
        // Hide YouTube URL input, show file chooser, and require file input
        youtubeContainer.style.display = "none";
        fileContainer.style.display = "block";
        fileInput.required = true;
      }
    }
  </script>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Convert form values to booleans
        use_youtube = bool(request.form.get('youtube'))
        downscale = bool(request.form.get('downscale'))
        faster = bool(request.form.get('faster'))
        use_mp3 = bool(request.form.get('use_mp3'))
        audio_only = bool(request.form.get('audio'))

        # Define output file path based on whether only audio is desired.
        if audio_only:
            output_filename = f"{uuid.uuid4()}.mp3" if use_mp3 else f"{uuid.uuid4()}.aac"
        else:
            output_filename = f"{uuid.uuid4()}.mp4"
        output_path = os.path.join(app.config['CONVERTED_FOLDER'], output_filename)

        # List of temporary files to delete after the response is sent.
        files_to_delete = []

        # YouTube branch
        if use_youtube:
            youtube_url = request.form.get('youtube_url')
            if not youtube_url:
                return "YouTube URL is required.", 400

            if downscale:
                # Download the worst quality version to disk.
                quality = 'worstaudio' if audio_only else 'worstvideo+worstaudio'
                yt_uuid = str(uuid.uuid4())
                yt_input_filename = yt_uuid + ".%(ext)s"
                yt_input_path = os.path.join(app.config['UPLOAD_FOLDER'], yt_input_filename)
                yt_dlp_cmd = ['yt-dlp', '-o', yt_input_path, '-f', quality, youtube_url]
                try:
                    subprocess.run(yt_dlp_cmd, check=True)
                except subprocess.CalledProcessError as e:
                    return f"An error occurred during YouTube download: {e}", 500

                # Locate the downloaded file (yt-dlp replaces %(ext)s with the actual extension).
                pattern = os.path.join(app.config['UPLOAD_FOLDER'], yt_uuid + ".*")
                downloaded_files = glob.glob(pattern)
                if not downloaded_files:
                    return "Failed to download YouTube video.", 500
                yt_input_file = downloaded_files[0]
                files_to_delete.append(yt_input_file)
                # Build FFmpeg command using the downloaded file.
                ffmpeg_cmd = ['ffmpeg', '-hwaccel', accel, '-y', '-i', yt_input_file] + extra.split()
            else:
                # Pipe best-quality output directly from yt-dlp.
                quality = 'bestaudio' if audio_only else 'best'
                yt_dlp_cmd = ['yt-dlp', '-o', '-', '-f', quality, youtube_url]
                ffmpeg_cmd = ['ffmpeg', '-hwaccel', accel, '-y', '-i', '-'] + extra.split()

            # Disable video stream if only audio is needed.
            if audio_only:
                ffmpeg_cmd.extend(['-vn'])

            # Add a preset for faster conversion if CUDA is not used.
            if not args.cuda and faster:
                ffmpeg_cmd.extend(['-preset', 'ultrafast'])

            # Configure audio encoding.
            configure_audio(ffmpeg_cmd, use_mp3)
            # Append the output file path.
            ffmpeg_cmd.append(output_path)

            if downscale:
                try:
                    subprocess.run(ffmpeg_cmd, check=True)
                except subprocess.CalledProcessError as e:
                    return f"An error occurred during conversion: {e}", 500
            else:
                try:
                    yt_proc = subprocess.Popen(yt_dlp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    subprocess.run(ffmpeg_cmd, stdin=yt_proc.stdout, check=True)
                    yt_proc.stdout.close()
                    yt_proc.wait()
                except subprocess.CalledProcessError as e:
                    return f"An error occurred during conversion: {e}", 500

        # File upload branch
        else:
            if 'video' not in request.files:
                return "No file part", 400
            file = request.files['video']
            if file.filename == '':
                return "No selected file", 400

            # Save the uploaded file.
            ext = os.path.splitext(file.filename)[1]
            input_filename = f"{uuid.uuid4()}{ext}"
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], input_filename)
            file.save(input_path)
            files_to_delete.append(input_path)

            # Build FFmpeg command for the uploaded file.
            cmd = ['ffmpeg', '-hwaccel', accel, '-y', '-i', input_path] + extra.split()
            if downscale:
                cmd.extend(['-vf', 'scale=144:-2'])
            if not args.cuda and faster:
                cmd.extend(['-preset', 'ultrafast'])
            if audio_only:
                cmd.extend(['-vn'])
                configure_audio(cmd, use_mp3)
            else:
                configure_audio(cmd, use_mp3)
            cmd.append(output_path)
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as e:
                return f"An error occurred during conversion: {e}", 500

        # Add the converted output file to the deletion list.
        files_to_delete.append(output_path)

        # Register a cleanup function to delete temporary files after the response is sent.
        @after_this_request
        def cleanup(response):
            for f in files_to_delete:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception as e:
                    app.logger.error("Error deleting temporary file %s: %s", f, e)
            return response

        # Serve the converted file as a downloadable attachment.
        return send_file(output_path, as_attachment=True)

    return render_template_string(html_template)

if __name__ == '__main__':
    app.run(debug=True, port=48716)