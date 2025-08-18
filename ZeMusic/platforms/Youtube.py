from ZeMusic.core.cache import (
    get_redis,
    extract_youtube_id,
    get_cached_gurl,
    set_cached_gurl,
    acquire_video_lock,
    release_video_lock,
    is_hard_video,
    set_hard_video,
)