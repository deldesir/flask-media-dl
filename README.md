# Flask-Media-Dl
This is a simple flask extension to download media from a url.


## Usage
```python
from flask import Flask
from flask_media_dl import MediaDownloader

app = Flask(__name__)
media_dl = MediaDownloader(app)

@app.route('/')
def index():
    return media_dl.download('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
```

## Credits
- This project uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) to download media from youtube.
- The API logic is heavily inspired by Openzim's [youtube](https://github.com/openzim/youtube) tool.