import requests
import time
import json
import threading
import re
import os
from tqdm import tqdm
from ebooklib import epub
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template_string, jsonify, request, send_from_directory
import webbrowser
from queue import Queue

app = Flask(__name__)

# 创建下载目录
if not os.path.exists('download'):
    os.makedirs('download')

# 全局变量存储下载状态和队列
download_status = {
    'total_chapters': 0,
    'downloaded': 0,
    'current_book': '',
    'is_downloading': False,
    'error': None,
    'last_update': 0,  # 添加时间戳字段
    'queue': [],  # 下载队列
    'queue_position': 0,  # 当前下载的位置
    'completed_books': []  # 已完成的书籍列表
}

# 从download目录加载已完成的书籍
def load_completed_books():
    completed_books = []
    if os.path.exists('download'):
        for filename in os.listdir('download'):
            if filename.endswith('.epub'):
                completed_books.append({
                    'name': os.path.splitext(filename)[0],
                    'filename': filename
                })
    return completed_books

# 初始化已完成书籍列表
download_status['completed_books'] = load_completed_books()

# HTML模板
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>番茄小说下载器</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, shrink-to-fit=no"/>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style>
        :root {
            --md-sys-color-primary: #6750A4;
            --md-sys-color-on-primary: #FFFFFF;
            --md-sys-color-primary-container: #EADDFF;
            --md-sys-color-on-primary-container: #21005D;
            --md-sys-color-surface: #FEF7FF;
            --md-sys-color-on-surface: #1C1B1F;
            --md-sys-color-surface-variant: #E7E0EC;
            --md-sys-color-outline: #79747E;
            --md-sys-elevation-1: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.14);
            --md-sys-elevation-2: 0 3px 6px rgba(0,0,0,0.15), 0 2px 4px rgba(0,0,0,0.12);
        }

        body {
            font-family: 'Roboto', sans-serif;
            margin: 0;
            background-color: var(--md-sys-color-surface);
            color: var(--md-sys-color-on-surface);
        }

        .top-app-bar {
            background-color: var(--md-sys-color-primary);
            color: var(--md-sys-color-on-primary);
            padding: 16px;
            box-shadow: var(--md-sys-elevation-1);
        }

        .container {
            max-width: 900px;
            margin: 24px auto;
            padding: 0 16px;
        }

        .card {
            background: #FFFFFF;
            border-radius: 28px;
            padding: 24px;
            margin: 16px 0;
            box-shadow: var(--md-sys-elevation-1);
        }

        .input-field {
            margin: 16px 0;
        }

        .input-field input {
            width: 100%;
            padding: 12px;
            border: 1px solid var(--md-sys-color-outline);
            border-radius: 4px;
            font-size: 16px;
            background: transparent;
        }

        .button {
            background-color: var(--md-sys-color-primary);
            color: var(--md-sys-color-on-primary);
            padding: 10px 24px;
            border: none;
            border-radius: 100px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            transition: all 0.2s;
        }

        .button:hover {
            box-shadow: var(--md-sys-elevation-2);
        }

        .progress-container {
            background: var(--md-sys-color-surface-variant);
            border-radius: 8px;
            height: 4px;
            margin: 16px 0;
            overflow: hidden;
        }

        .progress-bar {
            background: var(--md-sys-color-primary);
            height: 100%;
            width: 0;
            transition: width 0.3s ease;
        }

        .queue-item {
            background: var(--md-sys-color-surface-variant);
            padding: 16px;
            margin: 8px 0;
            border-radius: 16px;
        }

        .queue-item.active {
            background: var(--md-sys-color-primary-container);
            color: var(--md-sys-color-on-primary-container);
        }

        .book-card {
            background: #FFFFFF;
            border-radius: 28px;
            margin: 16px 0;
            overflow: hidden;
            box-shadow: var(--md-sys-elevation-1);
            transition: all 0.2s;
        }

        .book-card:hover {
            box-shadow: var(--md-sys-elevation-2);
        }

        .book-card-content {
            padding: 16px;
        }

        .book-card-actions {
            padding: 8px;
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        }

        .section-title {
            font-size: 24px;
            font-weight: 400;
            margin: 32px 0 16px;
            color: var(--md-sys-color-on-surface);
        }
    </style>
</head>
<body>
    <div class="top-app-bar">
        <h1 style="margin:0;font-size:22px;font-weight:400">番茄小说下载器</h1>
    </div>

    <div class="container">
        <div class="card">
            <div class="input-field">
                <input type="text" id="book_id" placeholder="输入book_id"/>
            </div>
            <div class="input-field">
                <input type="number" id="threads" value="8" min="1" max="16" placeholder="线程数"/>
            </div>
            <button class="button" onclick="addToQueue()">添加到队列</button>
        </div>

        <div class="card">
            <div id="status">未开始下载</div>
            <div class="progress-container">
                <div class="progress-bar" id="progress"></div>
            </div>
        </div>

        <h2 class="section-title">下载队列</h2>
        <div id="queue-list"></div>

        <h2 class="section-title">已完成的书籍</h2>
        <div id="completed-list"></div>
    </div>

    <script>
        let lastUpdate = 0;
        
        window.onload = function() {
            checkStatus();
        };
        
        function addToQueue() {
            const bookId = document.getElementById('book_id').value;
            const threads = document.getElementById('threads').value;
            fetch('/add_to_queue', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({book_id: bookId, threads: threads})
            })
            .then(response => response.json())
            .then(data => {
                if(data.error) {
                    alert('错误: ' + data.error);
                } else {
                    document.getElementById('book_id').value = '';
                    checkStatus();
                }
            });
        }

        function deleteBook(filename) {
            if(confirm('确定要删除这本书吗？')) {
                fetch('/delete_book/' + filename, {method: 'DELETE'})
                .then(response => response.json())
                .then(data => {
                    if(data.success) {
                        alert('删除成功');
                        checkStatus();
                    } else {
                        alert('删除失败: ' + data.error);
                    }
                });
            }
        }
        
        function checkStatus() {
            fetch('/status')
                .then(response => response.json())
                .then(data => {
                    const status = document.getElementById('status');
                    const progress = document.getElementById('progress');
                    const queueList = document.getElementById('queue-list');
                    const completedList = document.getElementById('completed-list');
                    
                    queueList.innerHTML = '';
                    data.queue.forEach((item, index) => {
                        const div = document.createElement('div');
                        div.className = 'queue-item' + (index === data.queue_position && data.is_downloading ? ' active' : '');
                        div.textContent = `${index + 1}. Book ID: ${item.book_id} (${item.threads} 线程)`;
                        queueList.appendChild(div);
                    });
                    
                    completedList.innerHTML = '';
                    data.completed_books.forEach(book => {
                        const card = document.createElement('div');
                        card.className = 'book-card';
                        
                        const content = document.createElement('div');
                        content.className = 'book-card-content';
                        content.textContent = book.name;
                        
                        const actions = document.createElement('div');
                        actions.className = 'book-card-actions';
                        
                        const downloadBtn = document.createElement('button');
                        downloadBtn.className = 'button';
                        downloadBtn.textContent = '下载';
                        downloadBtn.onclick = () => window.location.href = '/download/' + book.filename;
                        
                        const deleteBtn = document.createElement('button');
                        deleteBtn.className = 'button';
                        deleteBtn.style.backgroundColor = '#DC362E';
                        deleteBtn.textContent = '删除';
                        deleteBtn.onclick = () => deleteBook(book.filename);
                        
                        actions.appendChild(downloadBtn);
                        actions.appendChild(deleteBtn);
                        
                        card.appendChild(content);
                        card.appendChild(actions);
                        completedList.appendChild(card);
                    });
                    
                    if(data.error) {
                        alert('错误: ' + data.error);
                        return;
                    }
                    
                    if(data.last_update > lastUpdate) {
                        lastUpdate = data.last_update;
                        
                        if(data.is_downloading) {
                            const percent = (data.downloaded / data.total_chapters * 100).toFixed(1);
                            status.textContent = `正在下载 ${data.current_book}: ${data.downloaded}/${data.total_chapters} (${percent}%)`;
                            progress.style.width = percent + '%';
                            setTimeout(checkStatus, 1000);
                        } else if(data.downloaded > 0) {
                            status.textContent = '下载完成！';
                            progress.style.width = '100%';
                            setTimeout(checkStatus, 1000);
                        }
                    } else if(data.is_downloading || data.queue.length > 0) {
                        setTimeout(checkStatus, 1000);
                    }
                });
        }
    </script>
</body>
</html>
'''

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/status')
def status():
    # 每次请求状态时重新加载已完成书籍列表
    download_status['completed_books'] = load_completed_books()
    return jsonify(download_status)

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory('download', filename, as_attachment=True)

@app.route('/delete_book/<filename>', methods=['DELETE'])
def delete_book(filename):
    try:
        file_path = os.path.join('download', filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': '文件不存在'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/add_to_queue', methods=['POST'])
def add_to_queue():
    data = request.json
    book_id = data.get('book_id')
    threads = int(data.get('threads', 8))
    
    if not book_id:
        return jsonify({'error': '请输入book_id'})
    
    download_status['queue'].append({
        'book_id': book_id,
        'threads': threads
    })
    
    # 如果当前没有下载任务，启动下载
    if not download_status['is_downloading']:
        threading.Thread(target=process_queue).start()
    
    return jsonify({'status': 'added'})

def process_queue():
    while download_status['queue_position'] < len(download_status['queue']):
        current_item = download_status['queue'][download_status['queue_position']]
        
        # 重置状态
        download_status.update({
            'total_chapters': 0,
            'downloaded': 0,
            'current_book': '',
            'is_downloading': True,
            'error': None,
            'last_update': int(time.time())
        })
        
        # 下载当前书籍
        download_and_build_epub(current_item['book_id'], current_item['threads'])
        
        # 移动到下一本书
        download_status['queue_position'] += 1
        download_status['last_update'] = int(time.time())
    
    # 队列处理完成，重置状态
    download_status['queue'] = []
    download_status['queue_position'] = 0
    download_status['is_downloading'] = False
    download_status['last_update'] = int(time.time())

def get_chapter_infos(book_id):
    """获取章节信息（包含item_id和标题）"""
    url = "https://api.cenguigui.cn/api/tomato/api/all_items.php"
    params = {"book_id": book_id}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") != 0:
            raise Exception(f"API错误：{data.get('message')}")
        
        chapters = []
        # 遍历每个卷中的章节
        for volume in data["data"].get("chapterListWithVolume", []):
            for chapter in volume:
                chapters.append({
                    "item_id": chapter["itemId"],
                    "title": chapter["title"].strip()
                })
        return chapters
    
    except Exception as e:
        raise Exception(f"获取章节列表失败：{str(e)}")

def download_chapter(item_id):
    """下载章节内容并获取元数据"""
    url = f"https://fanqie.tutuxka.top/content.php?item_id={item_id}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") == 200:
            content_data = data.get("data", {})
            return {
                "content": content_data.get("content", ""),
                "author": content_data.get("author", "未知作者"),
                "book_name": content_data.get("book_name", "未知书名"),
                "pic": content_data.get("pic", "")
            }
        else:
            return None
    except Exception as e:
        print(f"下载章节 {item_id} 失败: {str(e)}")
        return None

def sanitize_filename(name):
    """去除文件名中的非法字符"""
    return re.sub(r'[\\/*?:"<>|]', '', name).strip()

def download_and_build_epub(book_id, thread_count=8):
    try:
        print("正在获取章节信息...")
        chapters = get_chapter_infos(book_id)
        total_chapters = len(chapters)
        print(f"共发现 {total_chapters} 个章节")
        
        download_status['total_chapters'] = total_chapters
        download_status['last_update'] = int(time.time())

        if total_chapters == 0:
            raise Exception("没有找到任何章节")

        # 初始化章节内容存储
        chapter_contents = [None] * total_chapters

        # 获取元数据（尝试前3个章节）
        metadata = {"author": "未知作者", "book_name": "未知书名", "pic": ""}
        for i in range(min(3, total_chapters)):
            result = download_chapter(chapters[i]["item_id"])
            if result:
                metadata["author"] = result.get("author", metadata["author"])
                metadata["book_name"] = result.get("book_name", metadata["book_name"])
                metadata["pic"] = result.get("pic", metadata["pic"])
                download_status['current_book'] = metadata["book_name"]
                download_status['last_update'] = int(time.time())
                break

        # 多线程下载所有章节
        print("开始下载章节内容...")
        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = []
            for idx in range(total_chapters):
                future = executor.submit(
                    download_chapter, 
                    chapters[idx]["item_id"]
                )
                futures.append((idx, future))

            for idx, future in futures:
                result = future.result()
                if result:
                    chapter_contents[idx] = {
                        "title": chapters[idx]["title"],
                        "content": result["content"]
                    }
                time.sleep(0.1)
                download_status['downloaded'] += 1
                download_status['last_update'] = int(time.time())

        # 创建EPUB
        print("正在生成EPUB文件...")
        book = epub.EpubBook()
        
        # 设置元数据
        book.set_title(metadata["book_name"])
        book.add_author(metadata["author"])
        book.set_language('zh')

        # 下载并添加封面
        cover_data = None
        if metadata["pic"]:
            try:
                response = requests.get(metadata["pic"], timeout=10)
                if response.status_code == 200:
                    cover_data = response.content
            except Exception as e:
                print(f"封面下载失败: {str(e)}")

        if cover_data:
            try:
                book.set_cover('cover.jpg', cover_data)
            except Exception as e:
                print(f"封面添加失败: {str(e)}")

        # 创建章节内容
        spine = ['nav']
        chapters_epub = []

        for idx, content_info in enumerate(chapter_contents):
            if not content_info or not content_info["content"]:
                continue

            chapter = epub.EpubHtml(
                title=content_info["title"],
                file_name=f'chapter_{idx}.xhtml',
                lang='zh'
            )
            
            # 处理换行符并使用BeautifulSoup清理内容
            content = content_info["content"].replace("\n", "<br/>")
            soup = BeautifulSoup(
                f"<h1>{content_info['title']}</h1>{content}", 
                'html.parser'
            )
            chapter.content = str(soup).encode('utf-8')
            
            book.add_item(chapter)
            chapters_epub.append(chapter)
            spine.append(chapter)

        # 设置目录和导航
        book.toc = tuple(chapters_epub)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = spine

        # 生成文件名
        filename = sanitize_filename(metadata["book_name"]) or f"book_{book_id}"
        epub_path = os.path.join('download', f"{filename}.epub")
        epub.write_epub(epub_path, book, {})
        print(f"EPUB文件已保存为：{epub_path}")
        
        # 更新已完成列表
        download_status['completed_books'] = load_completed_books()

    except Exception as e:
        error_msg = str(e)
        print(f"程序出错：{error_msg}")
        download_status['error'] = error_msg
    finally:
        download_status['last_update'] = int(time.time())

if __name__ == "__main__":
    webbrowser.open('http://127.0.0.1:5000')
    app.run(debug=True)
