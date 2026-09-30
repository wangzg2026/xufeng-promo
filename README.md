# xufeng-promo

这是一个面向美菜网第三方经销商的智能开票工具宣传与用户教育静态站。`index.html` 介绍服务价值、收费、开通流程与常见问题，`guide.html` 提供手机端图文操作指南；全站使用原生 HTML/CSS，无构建步骤和外部资源依赖。价格、退款规则和服务主体以 `pricing.json` 为事实源，页面通过 `assets/screenshots/step-01.png` 至 `step-06.png` 声明六个截图占位，最终图片由审核人补充或替换。

## 本地预览

在本目录运行：

```bash
python3 -m http.server 8900
```

然后在浏览器访问 `http://127.0.0.1:8900/`。提交前运行 `python3 check.py` 完成自动检查。

## Zeabur 静态部署

1. 将本目录作为一个独立 Git 仓库推送到代码托管平台，确认仓库根目录直接包含 `index.html`。
2. 在 Zeabur 新建项目并添加该 Git 仓库服务。
3. 选择静态站点部署；无需安装命令、构建命令或环境变量，发布目录填写仓库根目录。
4. 部署完成后使用 Zeabur 分配的子域名访问，逐页检查首页、操作指南、站内跳转和手机端排版。
5. 审核人补充或替换截图时，将六张图片按页面已声明的文件名放入 `assets/screenshots/`，再重新部署。

## PDF 版手册再生成

`manual.html` 内容变更后必须重新生成 `assets/manual.pdf`（check.py 会校验其存在）：

```bash
# 起本地服务器后执行（把 8905 换成实际端口）
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --disable-gpu --no-pdf-header-footer \
  --print-to-pdf=assets/manual.pdf "http://127.0.0.1:8905/manual.html"
```

导出后**必须**刷新指纹文件，否则 check.py 会判 PDF 陈旧：

```bash
python3 - <<'EOF'
import hashlib, json, pathlib
pathlib.Path("assets/manual.pdf.source").write_text(json.dumps({
    "manual_html": hashlib.sha256(pathlib.Path("manual.html").read_bytes()).hexdigest(),
    "manual_pdf": hashlib.sha256(pathlib.Path("assets/manual.pdf").read_bytes()).hexdigest(),
}, indent=2) + "\n")
EOF
```

check.py 读不了 PDF 文本层（纯 stdlib），靠这两个摘要拦住两种真实故障：改了 HTML 忘记
重新导出、以及把旧 PDF 拷回来顶替。再用 `pdftotext assets/manual.pdf -` 人工抽一遍确认：
不得出现上游接口返回码（8047/3001/8011 等），且能搜到「提交工单」入口。
