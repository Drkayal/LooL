"""
Integration Guide for YouTube Fallback System

To integrate this fallback system into your existing bot:

1. In your play command handler:
```python
from ZeMusic.utils.youtube_fallback import youtube_fallback
from ZeMusic.utils.arabic_messages import get_error_message

async def play_command_handler(message, url):
    try:
        # Check if we should try YouTube
        video_id = extract_video_id(url)
        
        if not await youtube_fallback.should_use_youtube(video_id):
            # Skip directly to alternatives
            alternative = await youtube_fallback.search_alternatives(url)
            if alternative:
                await message.reply(get_error_message("alternative_found"))
                return await play_alternative(alternative)
        
        # Try YouTube normally
        result = await download_from_youtube(url)
        youtube_fallback.mark_success(video_id)
        return result
        
    except Exception as e:
        if "Sign in to confirm" in str(e):
            # Handle bot detection
            alternative = await youtube_fallback.handle_youtube_failure(
                video_id, str(e), get_title_from_url(url)
            )
            
            if alternative:
                await message.reply(get_error_message("alternative_found"))
                return await play_alternative(alternative)
            else:
                await message.reply(get_error_message("no_alternative"))
                return None
        
        raise e  # Re-raise other errors
```

2. In your error handler:
```python
async def handle_youtube_error(error, message):
    if "Sign in to confirm" in str(error):
        await message.reply(get_error_message("bot_detected"))
    # ... handle other errors
```

3. Add periodic check for YouTube recovery:
```python
import asyncio

async def check_youtube_recovery():
    while True:
        try:
            # Test with a simple video
            test_result = await test_youtube_simple()
            if test_result:
                # YouTube is working again
                youtube_fallback.failed_videos.clear()
                await broadcast_message(get_error_message("youtube_working"))
        except:
            pass
        
        await asyncio.sleep(1800)  # Check every 30 minutes
```
"""
