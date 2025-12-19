拉取项目镜像

git clone https://github.com/zhangfanxp/image-dedup-system2.git

1、创建uv虚拟环境并激活

uv venv --python 3.12 && source .venv/bin/activate

2、安装项目依赖
uv pip install torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 \
  --index-url https://download.pytorch.org/whl/cu118

验证GPU
python - <<EOF
import torch
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0))
EOF

uv pip install -r requirements.txt

3、创建数据库

mysql -u root -p < setup.sql

4、把模型文件resnet50-11ad3fa6.pth拷贝至系统文件夹

mkdir -p ~/.cache/torch/hub/checkpoints
cp resnet50-11ad3fa6.pth ~/.cache/torch/hub/checkpoints/

5、运行命令

chatgpt版
streamlit run app/main.py

谷歌版
streamlit run app/app.py


----------------------------------------------------------------

app/db文件夹下的session.py中,要把mysql的root密码改为你本地设置的密码.

----------------------------------------------------------------


设置快速启动命令:

vi ~/.zshrc

文件末尾加入:

alias chachong='cd ~/Downloads/image-dedup-system && source .venv/bin/activate && streamlit run app/main.py'

保存并退出.

更新配置文件
source ~/.zshrc

命令行输入:
chachong 回车即可!

