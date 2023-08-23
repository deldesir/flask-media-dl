"""
    create project on Google Developer console
    Add Youtube Data API v3 to it
    Create credentials (Other non-UI, Public Data)
"""

import concurrent.futures
import datetime
import functools
from gettext import gettext as _
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import yt_dlp
from zimscraperlib.image.presets import WebpHigh
from zimscraperlib.video.presets import VideoMp4Low, VideoWebmLow

from flask_media_dl.platforms.youtube import (
    extract_playlists_details_from,
    get_videos_authors_info,
    get_videos_json,
    replace_titles,
    skip_deleted_videos,
    skip_outofrange_videos,
)
from flask_media_dl.constants import API_KEY, ROOT_DIR, logger
from flask_media_dl.processing import post_process_video, process_thumbnail
from flask_media_dl.utils import  get_id_type, load_json, save_json


class YoutubeDownload:
    """ Main class for the youtube plugin script. 
    
    This class is responsible for the whole process of scraping a youtube channel
    and converting it to a zim file.

    """
    def __init__(
        self,
        youtube_id,
        video_format,
        low_quality,
        resolution,
        all_subtitles,
        files,
        optimize,
        output_dir,
        debug,
        tmp_dir,
        keep_build_dir,
        max_concurrency,
        youtube_store,
        dateafter,
        custom_titles,
    ):
        # data-retrieval info
        self.youtube_id = youtube_id
        self.api_key = API_KEY
        self.files = files
        self.dateafter = dateafter

        # video-encoding info
        self.video_format = video_format
        self.low_quality = low_quality
        self.resolution = resolution

        # 
        self.optimize = optimize
        self.all_subtitles = all_subtitles
        self.custom_titles = custom_titles

        # directory setup
        self.output_dir = Path(output_dir).expanduser().resolve()
        if tmp_dir:
            tmp_dir = Path(tmp_dir).expanduser().resolve()
            tmp_dir.mkdir(parents=True, exist_ok=True)
        self.build_dir = Path(tempfile.mkdtemp(dir=tmp_dir))
        self.data_dir = self.output_dir / "data" / self.youtube_id / "build"

        # logging
        log = self.output_dir / "downloader.log"
        if not log.exists() or log.stat().st_size == 0:
            with open(log, "a") as f:
                f.write(f"Log file created at {datetime.datetime.now()}\n====================\n")
        if log.exists() and log.stat().st_size > 0:
            with open(log, "a") as f:
                f.write(
                    f"\n\n\nLog for {self.name} started on {datetime.datetime.now()}\n====================\n"
                )

        # process-related
        self.playlists = []
        self.uploads_playlist_id = None
        self.videos_ids = []
        self.main_channel_id = None  # use for branding

        # debug/devel options
        self.debug = debug
        self.keep_build_dir = keep_build_dir
        self.max_concurrency = max_concurrency

        # update youtube credentials store
        self.collection_type = get_id_type(self.youtube_id)
        youtube_store.update(
            build_dir=self.build_dir, api_key=self.api_key, cache_dir=self.cache_dir
        )

        # Optimization
        self.video_quality = "low" if self.low_quality else "high"

        self.ordered_videos_ids_list = None

    @property
    def root_dir(self):
        return ROOT_DIR

    @property
    def channels_dir(self):
        return self.build_dir.joinpath("channels")

    @property
    def cache_dir(self):
        return self.build_dir.joinpath("cache")

    @property
    def videos_dir(self):
        return self.build_dir.joinpath("videos")

    @property
    def is_single_channel(self):
        if self.collection_type == "channel" or self.collection_type == "user":
            return True
        return len(list({pl.creator_id for pl in self.playlists})) == 1

    @property
    def sorted_playlists(self):
        """sorted list of playlists (by title) but with Uploads one at first if any
        
        :return: sorted list of playlists
        :rtype: list

        """
        if len(self.playlists) < 2:
            return self.playlists

        sorted_playlists = sorted(self.playlists, key=lambda x: x.title)
        index = 0
        # make sure our Uploads, special playlist is first
        if self.uploads_playlist_id:
            try:
                index = [
                    index
                    for index, p in enumerate(sorted_playlists)
                    if p.playlist_id == self.uploads_playlist_id
                ][-1]
            except Exception:
                index = 0
        return (
            [sorted_playlists[index]] + sorted_playlists[0:index] + sorted_playlists[index + 1 :]
        )

    def run(self):
        """execute the build process

        :return: None
        
        """

        # validate dateafter input
        self.validate_dateafter_input()

        logger.info(f"preparing build folder at {self.build_dir.resolve()}")
        self.prepare_build_folder()

        # fail early if supplied branding files are missing
        self.check_branding_values()

        logger.info("compute list of playlists")
        self.extract_playlists()

        logger.info(
            ".. {} playlists:\n   {}".format(
                len(self.playlists),
                "\n   ".join([p.playlist_id for p in self.playlists]),
            )
        )

        logger.info("compute list of videos")
        self.extract_videos_info()

        nb_videos_msg = f".. {len(self.videos_ids)} videos"

        logger.info(f"{nb_videos_msg}.")

        if self.dateafter.start.year != 1:
            nb_videos_msg += f" in date range: {self.dateafter.start} - {datetime.date.today()}"
        logger.info(f"{nb_videos_msg}.")

        # download videos (and recompress)
        logger.info(
            "downloading all videos, subtitles and thumbnails "
            f"(concurrency={self.max_concurrency})"
        )
        logger.info(f"  format: {self.video_format}")
        logger.info(f"  quality: {self.video_quality}")
        logger.info(f"  generated-subtitles: {self.all_subtitles}")
        succeeded, failed = self.download_video_files(max_concurrency=self.max_concurrency)
        if failed:
            logger.error(f"{len(failed)} video(s) failed to download: {failed}")
            if len(failed) >= len(succeeded):
                logger.critical("More than half of videos failed. exiting")
                raise OSError("Too much videos failed to download")

        logger.info("retrieve channel-info for all videos (author details)")
        get_videos_authors_info(succeeded)

        logger.info("update general metadata")
        self.update_metadata()


    def validate_dateafter_input(self):
        """validate dateafter input

        :return: None

        """
        try:
            self.dateafter = yt_dlp.DateRange(self.dateafter)
        except Exception as exc:
            logger.error(
                "Invalid dateafter input. Valid dateafter format: "
                "YYYYMMDD or (now|today)[+-][0-9](day|week|month|year)(s)."
            )
            raise ValueError(f"Invalid dateafter input: {exc}")

    def validate_id(self):
        """validate youtube_id input

        :return: None

        """
        if self.collection_type == "channel" and len(self.youtube_id) > 24:
            raise ValueError("Invalid ChannelId")
        if "," in self.youtube_id and self.collection_type != "playlist":
            raise ValueError("Invalid YoutubeId")
        if not self.collection_type:
            raise ValueError("Invalid YoutubeId")

    def prepare_build_folder(self):
        """prepare build folder before we start downloading data
        
        - copy assets
        - copy JSON files to cache folder
        - create videos folder
        - create channels folder

        """

        # cache folder to store youtube-api results
        self.cache_dir.mkdir(exist_ok=True)

        # make videos placeholder
        self.videos_dir.mkdir(exist_ok=True)

        # make channels placeholder (profile files)
        self.channels_dir.mkdir(exist_ok=True)

        logger.info("copy JSON files to cache folder")
        # copy all JSON files in data_dir to cache_dir
        # to prevent fileExistsError when copying files,
        # we first remove all files in cache_dir
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
        for f in self.data_dir.glob("*.json"):
            shutil.copy(f, self.cache_dir)


    def extract_playlists(self):
        """
        prepare a list of Playlist from user request

        USER: we fetch the hidden channel associate to it
        CHANNEL (and USER): we grab all playlists + `uploads` playlist
        PLAYLIST: we retrieve from the playlist Id(s)

        :return: None
        """

        (
            self.playlists,
            self.main_channel_id,
            self.uploads_playlist_id,
        ) = extract_playlists_details_from(self.collection_type, self.youtube_id, self.optimize)

    def extract_videos_info(self):
        """
        process a list of videos ids from user request

        :return: None
        """
        logger.debug(f"found {len(self.files)} csv files")
        if self.files:
            for file in self.files:
                logger.debug(f"processing csv file: {file}")
                with open(file) as f:
                    lines = [line.strip().split(",") for line in f.readlines()]
                    if "video_id" not in lines[0]:
                        logger.debug("csv file does not have a header")
                        self.videos = [
                            {
                                "video_id": line[0].replace(
                                    "https://www.youtube.com/watch?v=", ""
                                ),
                                "title": line[1],
                                "video_size": line[5] if line[5] else 0,
                            }
                            for line in lines
                        ]
                    else:
                        logger.debug("csv file has a header")
                        self.videos = [
                            {
                                "video_id": line[0].replace(
                                    "https://www.youtube.com/watch?v=", ""
                                ),
                                "title": line[1],
                                "video_size": line[5] if line[5] else 0,
                            }
                            for line in lines[1:]
                        ]
                    videos_sizes_list = []
                    # sizes are human readable, we need to convert them to bytes
                    for video in self.videos:
                        if video["video_size"][-1:] == "K":
                            video["video_size"] = float(video["video_size"][:-2]) * 1024
                        elif video["video_size"][-1:] == "M":
                            video["video_size"] = float(video["video_size"][:-2]) * 1024 * 1024
                        elif video["video_size"][-1:] == "G":
                            video["video_size"] = (
                                float(video["video_size"][:-2]) * 1024 * 1024 * 1024
                            )
                        elif video["video_size"] == "0":
                            video["video_size"] = 0
                        else:
                            logger.error(f"Unknown size format: {video['video_size']}")
                            sys.exit(1)
                        videos_sizes_list.append(video["video_size"])
                    logger.debug(f"*** Videos sizes list: {videos_sizes_list}")
                    # total size of all videos in the csv file
                    self.total_size = sum(videos_sizes_list)

                    # check disk space
                    required_space = self.total_size * 2
                    disk_usage = shutil.disk_usage(os.getcwd())
                    available_space_gb = disk_usage.free / 1024 / 1024 / 1024
                    if available_space_gb < required_space:
                        logger.error(
                            f"*** Please free up {required_space - available_space_gb} GB of disk space"
                        )
                        logger.error(
                            "*** Or if you insist on attempting this job with constrained disk space, "
                            "hit any key within 10 seconds..."
                        )
                        try:
                            sys.stdin.read(1)
                        except KeyboardInterrupt:
                            logger.error("Exiting...")
                            sys.exit(1)
                        logger.error("Continuing...")
                    else:
                        logger.debug(f"*** Available space: {available_space_gb} GB")
                        logger.debug(f"*** Required space: {required_space} GB")

                    self.ordered_videos_ids_list = [video["video_id"] for video in self.videos]
                    logger.debug(f"*** Ordered video list: {self.ordered_videos_ids_list}")

                    self.videos_ids = [video["video_id"] for video in self.videos]
        if not self.files and self.youtube_id:
            all_videos = load_json(self.cache_dir, "videos.json")
            if all_videos is None:
                all_videos = {}
                for playlist in self.playlists:
                    videos_json = get_videos_json(playlist.playlist_id)
                    # filter in videos within date range and filter away deleted videos
                    # we replace videos titles if --custom-titles is used
                    if self.custom_titles:
                        replace_titles(videos_json, self.custom_titles)
                    # we filter out videos that are out of range and deleted
                    skip_outofrange = functools.partial(skip_outofrange_videos, self.dateafter)
                    filter_videos = filter(skip_outofrange, videos_json)
                    filter_videos = filter(skip_deleted_videos, filter_videos)
                    all_videos.update({v["contentDetails"]["videoId"]: v for v in filter_videos})
                save_json(self.cache_dir, "videos", all_videos)
                self.videos_ids = [*all_videos.keys()]  # unpacking so it's subscriptable

    def download_video_files(self, max_concurrency):
        """
        download video files

        :return: None
        """
        audext, vidext = {"webm": ("webm", "webm"), "mp4": ("m4a", "mp4")}[self.video_format]

        # prepare options which are shared with every downloader
        options = {
            "cachedir": self.videos_dir,
            "writethumbnail": True,
            "write_all_thumbnails": False,
            "writesubtitles": True,
            "allsubtitles": True,
            "subtitlesformat": "vtt",
            "keepvideo": False,
            "ignoreerrors": False,
            "retries": 20,
            "fragment-retries": 50,
            "skip-unavailable-fragments": True,
            # "external_downloader": "aria2c",
            # "external_downloader_args": ["--max-tries=20", "--retry-wait=30"],
            "outtmpl": str(self.videos_dir.joinpath("%(id)s", "video.%(ext)s")),
            "preferredcodec": self.video_format,
            "format": f"best[ext={vidext}]/"
            f"bestvideo[ext={vidext}]+bestaudio[ext={audext}]/best"
            if not self.resolution
            else f"bestvideo[height<={self.resolution}][ext={vidext}]+bestaudio[ext={audext}]/best[height<={self.resolution}]",
            "y2z_videos_dir": self.videos_dir,
        }
        if self.all_subtitles:
            options.update({"writeautomaticsub": True})

        # find number of actuall parallel workers
        nb_videos = len(self.videos_ids)
        concurrency = nb_videos if nb_videos < max_concurrency else max_concurrency

        # short-circuit concurency if we have only one thread (can help debug)
        if concurrency <= 1:
            return self.download_video_files_batch(options, self.videos_ids)

        # prepare out videos_ids batches
        def get_slot():
            n = 0
            while True:
                yield n
                n += 1
                if n >= concurrency:
                    n = 0

        batches = [[] for _ in range(0, concurrency)]
        slot = get_slot()
        for video_id in self.videos_ids:
            batches[next(slot)].append(video_id)

        overall_succeeded = []
        overall_failed = []
        # execute the batches concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            fs = [
                executor.submit(self.download_video_files_batch, options, videos_ids)
                for videos_ids in batches
            ]
            done, not_done = concurrent.futures.wait(
                fs, return_when=concurrent.futures.ALL_COMPLETED
            )

            # we have some `not_done` batches, indicating errors within
            if not_done:
                logger.critical("Not all video-processing batches completed. Cancelling…")
                for future in not_done:
                    exc = future.exception()
                    if exc:
                        logger.exception(exc)
                        raise exc

            # retrieve our list of successful/failed video_ids
            for future in done:
                succeeded, failed = future.result()
                overall_succeeded += succeeded
                overall_failed += failed

        # remove left-over files for failed downloads
        logger.debug(f"removing left-over files of {len(overall_failed)} failed videos")
        for video_id in overall_failed:
            shutil.rmtree(self.videos_dir.joinpath(video_id), ignore_errors=True)

        return overall_succeeded, overall_failed

    def download_video(self, video_id, options):
        """
        download the video from cache/youtube and return True if successful
        
        :param video_id: the video id to download
        :param options: the options to download with
        :return: whether it successfully downloaded the video
        """

        preset = {"mp4": VideoMp4Low}.get(self.video_format, VideoWebmLow)()
        options_copy = options.copy()
        video_location = options_copy["y2z_videos_dir"].joinpath(video_id)
        video_path = video_location.joinpath(f"video.{self.video_format}")

        try:
            # skip downloading the thumbnails
            options_copy.update(
                {
                    "writethumbnail": False,
                    "writesubtitles": False,
                    "allsubtitles": False,
                    "writeautomaticsub": False,
                }
            )
            with yt_dlp.YoutubeDL(options_copy) as ydl:
                ydl.download([video_id])
            post_process_video(
                video_location,
                video_id,
                preset,
                self.video_format,
                self.low_quality,
            )
        except (
            yt_dlp.utils.DownloadError,
            FileNotFoundError,
            subprocess.CalledProcessError,
        ) as exc:
            logger.error(f"Video file for {video_id} could not be downloaded")
            logger.debug(exc)
            return False

    def download_thumbnail(self, video_id, options):
        """
        download the thumbnail from youtube and return True if successful
        
        :param video_id: the video id to download
        :param options: the options to download with
        :return: whether it successfully downloaded the thumbnail
        """

        preset = WebpHigh()
        options_copy = options.copy()
        video_location = options_copy["y2z_videos_dir"].joinpath(video_id)
        thumbnail_path = video_location.joinpath("video.webp")

        try:
            # skip downloading the video
            options_copy.update(
                {
                    "skip_download": True,
                    "writesubtitles": False,
                    "allsubtitles": False,
                    "writeautomaticsub": False,
                }
            )
            with yt_dlp.YoutubeDL(options_copy) as ydl:
                ydl.download([video_id])
            process_thumbnail(thumbnail_path, preset)
        except (
            yt_dlp.utils.DownloadError,
            FileNotFoundError,
            subprocess.CalledProcessError,
        ) as exc:
            logger.error(f"Thumbnail for {video_id} could not be downloaded")
            logger.debug(exc)
            return False

    def download_subtitles(self, video_id, options):
        """
        download subtitles for a video

        :param video_id: the video id to download
        :param options: the options to download with
        :return: whether it successfully downloaded the subtitles
        """

        options_copy = options.copy()
        options_copy.update({"skip_download": True, "writethumbnail": False})
        try:
            with yt_dlp.YoutubeDL(options_copy) as ydl:
                ydl.download([video_id])
        except Exception:
            logger.error(f"Could not download subtitles for {video_id}")

    def download_video_files_batch(self, options, videos_ids):
        """
        download video file and thumbnail for all videos in batch

        :param options: the options to download with
        :param videos_ids: the video ids to download
        :return: a tuple of succeeded and failed video ids
        """

        succeeded = []
        failed = []
        for video_id in videos_ids:
            if self.download_video(video_id, options) and self.download_thumbnail(
                video_id, options
            ):
                self.download_subtitles(video_id, options)
                succeeded.append(video_id)
            else:
                failed.append(video_id)
        return succeeded, failed