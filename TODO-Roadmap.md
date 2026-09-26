# Roadmap





# TODO
- [ ] 2026-09-26：功能区添加打包，将项目文件夹里的flet程序（比如：D:\Projects\cs-markdown-editor）打包到`D:\Softwares`的对应路径（比如：D:\Softwares\cs-markdown-editor）下，若对应路径文件夹下已存在文件，提示是否删除。打包时先运行 flet clean，再运行打包命令（根据不同项目进行适配，artifact、product为项目名称）：flet build windows "D:\Projects\cs-markdown-editor"  --artifact 文档编辑器 --cleanup-app --cleanup-app-files build --cleanup-package-files build --cleanup-packages --company cstos.com --copyright ShawnChen --output "D:\Softwares\cs-markdown-editor" --product 文档编辑器 --python-version 3.12 --template "D:\Softwares\flet-template-dir\flet-build-template"
- [x] 2026-09-26：程序整体使用本地字体assets\fonts\AlibabaPuHuiTi-3-55-Regular.otf
- [x] 2026-09-26：修复推送，改为推送到所有已配置的远程；未配置远程时给出明确提示
- [x] 2026-09-27：配置日志器，对命令运行与命令行输出做日志记录（可追溯操作、可定位报错）
