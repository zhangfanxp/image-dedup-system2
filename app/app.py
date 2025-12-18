import streamlit as st
import torch
from pathlib import Path
import shutil
from PIL import Image, ImageChops, UnidentifiedImageError

# 导入你的工具函数
from utils.unzip import unzip
from utils.image_scan import scan_images
from utils.hash import calc_md5
from utils.similarity import is_similar_cnn
from db.image_repo import get_image_by_md5
from db.session import SessionLocal
from sqlalchemy import text

# =====================
# 1. 页面与目录配置
# =====================
st.set_page_config(page_title="图片查重与入库系统", layout="wide")

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
TEMP_DIR = BASE_DIR / "temp"
LIB_DIR = BASE_DIR / "image_library"

for d in [UPLOAD_DIR, TEMP_DIR, LIB_DIR]: d.mkdir(exist_ok=True)
VALID_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}

if "results" not in st.session_state:
    st.session_state.results = None

# =====================
# 2. 核心组件：图片卡片 (局部刷新)
# =====================
@st.fragment
def render_image_card(r, idx):
    """渲染单张图片卡片，支持误报纠正"""
    status_style = {
        "重复": "🔴",
        "相似": "🟠",
        "正常": "🟢"
    }
    
    st.markdown(f"### {status_style.get(r['status'], '⚪')} {r['status']}")
    st.image(str(r["path"]), use_container_width=True)
    st.caption(f"文件名: {r['path'].name}")
    
    if r["status"] == "相似":
        st.warning(f"相似度: {r['similar_ratio']}%")
        with st.expander("🔍 对比库中图"):
            lib_img_path = LIB_DIR / r["db_similar_image"]
            c1, c2 = st.columns(2)
            with c1: st.image(str(r["path"]), caption="上传图")
            with c2: st.image(str(lib_img_path), caption="库中相似图")
            
            if st.button("✅ 误报，这是新照片", key=f"fix_{idx}"):
                st.session_state.results[idx]["status"] = "正常"
                st.rerun()

# =====================
# 3. 侧边栏与检测引擎
# =====================
with st.sidebar:
    st.title("⚙️ 环境监控")
    device = "CUDA GPU" if torch.cuda.is_available() else "CPU"
    st.info(f"当前计算设备: {device}")
    
    st.divider()
    st.markdown("### 检测阈值设置")
    threshold = st.slider("CNN 相似度判定阈值", 0.70, 0.99, 0.85, 0.01)

st.title("📷 图片查重系统 (CNN + CUDA)")

uploaded = st.file_uploader("第一步：上传 ZIP 压缩包", type=["zip"])
if uploaded:
    zip_path = UPLOAD_DIR / uploaded.name
    with open(zip_path, "wb") as f:
        f.write(uploaded.getbuffer())

# =====================
# 4. 执行检测逻辑
# =====================
if uploaded and st.button("🚀 第二步：开始检测", type="primary"):
    with st.spinner("⏳ 正在解压并分析视觉特征..."):
        # 清理并解压
        if TEMP_DIR.exists(): shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir()
        unzip(zip_path, TEMP_DIR)

        all_files = [f for f in scan_images(TEMP_DIR) if f.suffix.lower() in VALID_EXTS]
        library_images = [f for f in LIB_DIR.iterdir() if f.suffix.lower() in VALID_EXTS]
        
        results = []
        p_bar = st.progress(0.0)
        
        for i, img in enumerate(all_files):
            # 1. MD5 查重 (绝对重复)
            md5 = calc_md5(img)
            exists_in_db = get_image_by_md5(md5)
            
            res = {"path": img, "md5": md5, "status": "正常", "db_similar_image": None, "similar_ratio": None}
            
            if exists_in_db:
                res["status"] = "重复"
            else:
                # 2. CNN 相似检测 (视觉相似)
                for lib_img in library_images:
                    try:
                        is_sim, ratio = is_similar_cnn(img, lib_img, threshold=threshold)
                        if is_sim:
                            res["status"] = "相似"
                            res["similar_ratio"] = int(ratio * 100)
                            res["db_similar_image"] = lib_img.name
                            break
                    except: continue
            
            results.append(res)
            p_bar.progress((i + 1) / len(all_files))
        
        # 优先级排序
        results.sort(key=lambda x: {"相似": 0, "重复": 1, "正常": 2}.get(x["status"], 3))
        st.session_state.results = results

# =====================
# 5. 结果展示与入库 (核心改进)
# =====================
if st.session_state.results:
    res_list = st.session_state.results
    
    # --- 统计面板 ---
    total = len(res_list)
    dup_count = sum(1 for r in res_list if r["status"] == "重复")
    sim_count = sum(1 for r in res_list if r["status"] == "相似")
    new_count = sum(1 for r in res_list if r["status"] == "正常")

    st.markdown("### 📊 检测统计报告")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📦 总扫描量", total)
    c2.metric("🔴 重复(MD5)", dup_count)
    c3.metric("🟠 相似(CNN)", sim_count)
    c4.metric("🟢 新照片(可入库)", new_count)
    
    # 逻辑校验提示
    if total == (dup_count + sim_count + new_count):
        st.caption("✅ 数据校验通过：总数 = 重复 + 相似 + 新照片")

    # --- 入库按钮 ---
    if new_count > 0:
        if st.button(f"📥 确认将 {new_count} 张新照片入库", type="primary", use_container_width=True):
            session = SessionLocal()
            try:
                with st.status("正在同步数据到图片库...", expanded=True) as status:
                    actual_inserted = 0
                    for r in res_list:
                        if r["status"] == "正常":
                            # 文件搬运
                            dest_name = f"{r['md5']}_{r['path'].name}"
                            dest_path = LIB_DIR / dest_name
                            shutil.copy2(r["path"], dest_path)
                            
                            # 获取规格
                            with Image.open(dest_path) as im:
                                w, h = im.size
                            
                            # 数据库写入
                            session.execute(
                                text("INSERT INTO image_library (image_name, image_path, md5, width, height) VALUES (:n, :p, :m, :w, :h)"),
                                {"n": dest_name, "p": str(dest_path), "m": r["md5"], "w": w, "h": h}
                            )
                            actual_inserted += 1
                    
                    session.commit()
                    status.update(label=f"🎉 成功！{actual_inserted} 张新图片已归档，重复及相似图片已被过滤。", state="complete")
                
                # 重置状态以刷新库
                st.session_state.results = None
                st.balloons()
                st.rerun()
            except Exception as e:
                session.rollback()
                st.error(f"入库失败: {e}")
            finally:
                session.close()
    else:
        st.success("本次上传的所有图片在库中均已存在（重复或相似），无需重复入库。")

    # --- 结果网格 ---
    st.divider()
    grid = st.columns(4)
    for idx, r in enumerate(res_list):
        with grid[idx % 4]:
            render_image_card(r, idx)
else:
    st.info("👋 欢迎使用！请在上方上传 ZIP 包开始图片合规性检测。")