import base64
import mimetypes
import os
import requests

def upload_files(files: list, upload_path: str, overwrite=False):
    """
    上传多个文件

    :param files: 文件路径的列表
    :param upload_path: 上传的目标路径
    :param overwrite: 是否覆盖已有文件
    :return: 上传结果
    """
    UPLOAD_FILE_URL = os.getenv('UPLOAD_FILE_URL', None)
    if UPLOAD_FILE_URL is None:
        return {"status": "error", "data": {"code": 500, "msg": "UPLOAD_FILE_URL 环境变量未设置"}}
    
    try:
        # 准备要上传的文件
        file_data = []
        for file in files:
            file_name = os.path.basename(file)
            file_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            with open(file, 'rb') as f:
                # 使用三元组 (文件名, 文件对象, 文件类型)
                file_data.append(("files", (file_name, f.read(), file_type)))

        # 添加其他表单字段数据
        extra_data = {
            "file_path": upload_path,
            "overwrite": overwrite
        }

        # 发送 POST 请求
        response = requests.post(UPLOAD_FILE_URL, data=extra_data, files=file_data)

        # 检查返回结果
        if response.status_code != 200:
            return {"status": "error", "data": response.json()}
        else:
            return {"status": "success", "data": response.json()}
    except requests.RequestException as http_err:
        return {"status": "error", "data": {"code": 500, "msg": f"HTTP error occurred: {http_err}"}}
    except Exception as err:
        return {"status": "error", "data": {"code": 500, "msg": f"An error occurred: {err}"}}
    

def download_image(url):
    """
    下载图片的函数。
    
    参数:
        url (str): 图片的 URL
    
    返回:
        格式化后的 Base64 编码的图片数据
    """
    # 下载图片的逻辑
    try:
        # 获取图像数据
        response = requests.get(url)
        response.raise_for_status()  # 检查是否成功请求
        
        # 将图像数据转换为 Base64 编码
        base64_image = base64.b64encode(response.content).decode('utf-8')
        
        return f"data:image/png;base64,{base64_image}"
    except requests.exceptions.RequestException as e:
        return None