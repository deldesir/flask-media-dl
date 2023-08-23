"""
This is a flask extension for downloading media files from video hosting sites like YouTube.
"""
from flask import current_app
from flask_media_dl.downloaders.youtube_downloader import YoutubeDownload


class MediaDownloader:
    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        # Initialize your extension with the app
        app.extensions['media_dl'] = self

    def download_media(self, youtube_id, video_format, low_quality, resolution, all_subtitles, files, optimize, output_dir, fname, debug, tmp_dir, keep_build_dir, max_concurrency, youtube_store, language, locale_name, dateafter, use_any_optimized_version, s3_url_with_credentials, custom_titles, title=None, description=None, creator=None, publisher=None, name=None, profile_image=None, banner_image=None, main_color=None, secondary_color=None):
        # Initialize the YoutubeDownload instance
        downloader = YoutubeDownload(
            youtube_id=youtube_id,
            video_format=video_format,
            low_quality=low_quality,
            resolution=resolution,
            all_subtitles=all_subtitles,
            files=files,
            optimize=optimize,
            output_dir=output_dir,
            fname=fname,
            debug=debug,
            tmp_dir=tmp_dir,
            keep_build_dir=keep_build_dir,
            max_concurrency=max_concurrency,
            youtube_store=youtube_store,
            language=language,
            locale_name=locale_name,
            dateafter=dateafter,
            use_any_optimized_version=use_any_optimized_version,
            s3_url_with_credentials=s3_url_with_credentials,
            custom_titles=custom_titles,
            title=title,
            description=description,
            creator=creator,
            publisher=publisher,
            name=name,
            profile_image=profile_image,
            banner_image=banner_image,
            main_color=main_color,
            secondary_color=secondary_color
        )

        # Run the download process
        downloader.run()

def create_media_dl():
    return MediaDownloader(current_app)

