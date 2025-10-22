import yt_dlp
import re
from typing import Optional, Dict, List
import os
import logging
import asyncio
import httpx

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def upload_to_fileio(filepath: str) -> Optional[str]:
    try:
        logger.info(f"Загрузка файла на file.io: {filepath}")
        
        async with httpx.AsyncClient(timeout=600.0) as client:
            with open(filepath, 'rb') as f:
                files = {'file': f}
                response = await client.post('https://file.io', files=files)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success'):
                        link = data.get('link')
                        logger.info(f"Файл успешно загружен: {link}")
                        return link
                else:
                    logger.error(f"Ошибка загрузки на file.io: {response.status_code}")
                    return None
    except Exception as e:
        logger.error(f"Ошибка при загрузке на file.io: {str(e)}", exc_info=True)
        return None

async def extract_tiktok_info_api(url: str) -> Optional[Dict]:
    try:
        logger.info(f"Extracting TikTok info via API: {url}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                'https://www.tikwm.com/api/',
                params={'url': url, 'hd': 1}
            )
            
            if response.status_code != 200:
                logger.error(f"TikWM API error: {response.status_code}")
                return None
            
            data = response.json()
            
            if data.get('code') != 0:
                logger.error(f"TikWM API returned error code: {data.get('code')}")
                return None
            
            video_data = data.get('data', {})
            
            title = video_data.get('title', 'TikTok Video')
            duration = video_data.get('duration', 0)
            thumbnail = video_data.get('cover', '')
            
            formats_list = []
            if video_data.get('hdplay'):
                formats_list.append({'quality': 'HD', 'format_id': 'hd', 'height': 1080})
            if video_data.get('play'):
                formats_list.append({'quality': 'SD', 'format_id': 'sd', 'height': 720})
            
            logger.info(f"Successfully extracted TikTok info: {title}")
            
            return {
                'title': title,
                'duration': duration,
                'thumbnail': thumbnail,
                'platform': 'tiktok',
                'formats': formats_list,
                'url': url,
                'api_data': video_data
            }
    except Exception as e:
        logger.error(f"Error extracting TikTok info via API: {str(e)}", exc_info=True)
        return None

async def extract_video_info_async(url: str) -> Optional[Dict]:
    """Извлекает информацию о видео (TikTok через API, Pinterest через yt-dlp)"""
    platform = 'pinterest' if 'pinterest.com' in url or 'pin.it' in url else 'tiktok'
    
    if platform == 'tiktok':
        return await extract_tiktok_info_api(url)
    
    try:
        # Улучшенные настройки для Pinterest
        ydl_opts = {
            'quiet': False,
            'no_warnings': False,
            'extract_flat': False,
            'socket_timeout': 30,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'referer': 'https://www.pinterest.com/',
            'http_headers': {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0',
            },
            # Игнорируем SSL ошибки для Pinterest
            'nocheckcertificate': True,
        }
        
        logger.info(f"Extracting info for {platform} video: {url}")
        
        def extract_sync():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, extract_sync)
        
        if not info:
            logger.error("No info extracted from Pinterest URL")
            return None
        
        formats_list = []
        if info.get('formats'):
            seen_heights = set()
            for f in info['formats']:
                height = f.get('height')
                vcodec = f.get('vcodec', 'none')
                # Берем только видео форматы (не только аудио)
                if height and height not in seen_heights and vcodec != 'none':
                    quality = f"{height}p"
                    formats_list.append({
                        'quality': quality,
                        'format_id': f['format_id'],
                        'height': height
                    })
                    seen_heights.add(height)
            
            formats_list.sort(key=lambda x: x['height'])
        
        # КРИТИЧЕСКАЯ ПРОВЕРКА: если форматов нет, добавляем "best"
        if not formats_list:
            logger.warning("No video formats found, adding fallback 'best' format")
            formats_list.append({
                'quality': 'best',
                'format_id': 'best',
                'height': 720
            })
        
        thumbnail = info.get('thumbnail', '')
        title = info.get('title', 'Pinterest Video')
        
        logger.info(f"Successfully extracted info: {title} with {len(formats_list)} formats")
        
        return {
            'title': title,
            'duration': info.get('duration', 0),
            'thumbnail': thumbnail,
            'platform': platform,
            'formats': formats_list,
            'url': url
        }
    except Exception as e:
        logger.error(f"Error extracting video info from {url}: {str(e)}", exc_info=True)
        return None

def is_valid_url(url: str) -> bool:
    pinterest_pattern = r'(https?://)?(www\.)?(pinterest\.com|pin\.it)/.+'
    tiktok_pattern = r'(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/.+'
    
    return bool(re.match(pinterest_pattern, url)) or bool(re.match(tiktok_pattern, url))

def extract_urls(text: str) -> List[str]:
    url_pattern = r'https?://[^\s]+'
    urls = re.findall(url_pattern, text)
    return [url for url in urls if is_valid_url(url)]

async def download_tiktok_via_api(url: str, quality: Optional[str] = None, audio_only: bool = False) -> Optional[str]:
    try:
        logger.info(f"Downloading TikTok via API: {url}, quality={quality}, audio_only={audio_only}")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                'https://www.tikwm.com/api/',
                params={'url': url, 'hd': 1}
            )
            
            if response.status_code != 200:
                logger.error(f"TikWM API error: {response.status_code}")
                return None
            
            data = response.json()
            
            if data.get('code') != 0:
                logger.error(f"TikWM API returned error code: {data.get('code')}")
                return None
            
            video_data = data.get('data', {})
            
            if audio_only:
                download_url = video_data.get('music')
                if not download_url:
                    logger.error("No audio URL found in API response")
                    return None
                file_ext = 'mp3'
            else:
                if quality == 'sd':
                    download_url = video_data.get('play')
                    logger.info("Using SD quality (user requested)")
                elif quality == 'hd' or quality is None:
                    download_url = video_data.get('hdplay') or video_data.get('play')
                    logger.info(f"Using HD quality (available: {bool(video_data.get('hdplay'))})")
                else:
                    download_url = video_data.get('hdplay') or video_data.get('play')
                
                if not download_url:
                    logger.error("No video URL found in API response")
                    return None
                file_ext = 'mp4'
            
            os.makedirs('downloads', exist_ok=True)
            
            video_id = re.search(r'/video/(\d+)', url)
            if video_id:
                filename = f"downloads/{video_id.group(1)}.{file_ext}"
            else:
                import hashlib
                filename = f"downloads/{hashlib.md5(url.encode()).hexdigest()}.{file_ext}"
            
            logger.info(f"Downloading from: {download_url[:100]}...")
            
            video_response = await client.get(download_url)
            
            if video_response.status_code != 200:
                logger.error(f"Failed to download file: {video_response.status_code}")
                return None
            
            with open(filename, 'wb') as f:
                f.write(video_response.content)
            
            file_size = os.path.getsize(filename) / (1024 * 1024)
            logger.info(f"Successfully downloaded: {filename} ({file_size:.2f} MB)")
            
            return filename
            
    except Exception as e:
        logger.error(f"Error downloading TikTok via API: {str(e)}", exc_info=True)
        return None

async def download_video(url: str, quality: Optional[str] = None, audio_only: bool = False) -> Optional[str]:
    """
    Скачивает видео с TikTok или Pinterest
    
    Args:
        url: URL видео
        quality: качество (например '720p', 'best')
        audio_only: скачивать только аудио
    
    Returns:
        Путь к скачанному файлу или None при ошибке
    """
    try:
        platform = 'pinterest' if 'pinterest.com' in url or 'pin.it' in url else 'tiktok'
        
        logger.info(f"Starting download from {platform}: {url}, quality={quality}, audio_only={audio_only}")
        
        if platform == 'tiktok':
            return await download_tiktok_via_api(url, quality, audio_only)
        
        # Улучшенные настройки для Pinterest
        base_opts = {
            'quiet': False,
            'no_warnings': False,
            'socket_timeout': 30,
            'retries': 5,
            'fragment_retries': 5,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'referer': 'https://www.pinterest.com/',
            'http_headers': {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0',
            },
            'nocheckcertificate': True,
        }
        
        if audio_only:
            ydl_opts = {
                **base_opts,
                'format': 'bestaudio/best',
                'outtmpl': 'downloads/%(id)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
        else:
            if quality and quality != 'best':
                height = quality.replace('p', '')
                ydl_opts = {
                    **base_opts,
                    'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best',
                    'outtmpl': 'downloads/%(id)s.%(ext)s',
                    'merge_output_format': 'mp4',
                }
            else:
                ydl_opts = {
                    **base_opts,
                    'format': 'bestvideo+bestaudio/best',
                    'outtmpl': 'downloads/%(id)s.%(ext)s',
                    'merge_output_format': 'mp4',
                }
        
        os.makedirs('downloads', exist_ok=True)
        
        def download_sync():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    logger.error("No info returned from yt-dlp during download")
                    return None
                    
                filename = ydl.prepare_filename(info)
                
                if audio_only:
                    filename = filename.rsplit('.', 1)[0] + '.mp3'
                elif not filename.endswith('.mp4'):
                    base_filename = filename.rsplit('.', 1)[0]
                    if os.path.exists(base_filename + '.mp4'):
                        filename = base_filename + '.mp4'
                
                return filename
        
        loop = asyncio.get_event_loop()
        filename = await loop.run_in_executor(None, download_sync)
        
        if not filename:
            logger.error("Download function returned None")
            return None
        
        if filename and os.path.exists(filename):
            file_size = os.path.getsize(filename) / (1024 * 1024)
            logger.info(f"Successfully downloaded: {filename} ({file_size:.2f} MB)")
            return filename
        else:
            logger.error(f"Download failed: file not found at {filename}")
            return None
            
    except Exception as e:
        logger.error(f"Error downloading video from {url}: {str(e)}", exc_info=True)
        return None

def format_duration(seconds) -> str:
    if seconds is None:
        return "Неизвестно"
    
    seconds = int(seconds)
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"
