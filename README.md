# Git Log Graph Viewer

一個用 Python + PySide6 寫成的輕量級 Git commit graph 圖形化檢視工具。只會執行 `git log` 等**唯讀**指令，不會對你的 repository 做任何寫入或變更操作。

## 功能特色

- **Commit Graph 視覺化**：用顏色區分不同分支線（lane），呈現分叉與合併的關係
- **點擊取得 Focus**：點擊 commit 節點或旁邊的文字列，會高亮該節點，其餘 commit 自動調暗，方便聚焦觀察；點擊空白處可取消 focus
- **Commit 詳細資訊面板**：下方面板顯示完整 hash、作者、日期、parent commit、refs、完整 commit message（含多行內容），文字可選取複製
- **左側 Branch List**：列出本地分支，預設分支（依 origin HEAD 或 main/master）會自動排在最上面；點擊分支會標示出該分支可追溯到的所有 commit，不會重新排列 graph 版面
- **路徑記憶**：手動輸入或透過瀏覽視窗選取過的 repo 路徑會自動記住，下次開啟可直接從下拉選單選取，並自動正規化正反斜線寫法避免重複紀錄
- **字體大小調整**：工具列可即時調整字體大小，並會記住設定，重開程式不需要再調一次
- **WSL 路徑支援**：可直接輸入或透過瀏覽視窗開啟 `\\wsl$\...` 這類路徑
- **Safe Directory 友善提示**：偵測到 Git 的 "dubious ownership" 錯誤時，會自動解析建議指令並詢問是否要代為執行 `git config --global --add safe.directory`

## 安裝需求

- Python 3.9 以上
- [PySide6](https://pypi.org/project/PySide6/)
- Git（需可在系統 PATH 中執行）

```bash
pip install PySide6
```

> 在 Windows 上若安裝過程出現路徑過長的錯誤，請參考 [啟用 Windows 長路徑支援](https://pip.pypa.io/warnings/enable-long-paths)。

## 使用方式

```bash
python git_graph_viewer.py [repo路徑]
```

也可以不帶參數直接執行，啟動後再用工具列的「開啟 Repo...」選擇資料夾。

```bash
python git_graph_viewer.py C:\path\to\your\repo
```

## 操作說明

| 操作 | 說明 |
|---|---|
| 點擊 commit 節點 / 文字 | 取得 focus，detail panel 顯示完整資訊；再點一次取消 |
| 點擊 graph 空白處 | 取消目前的 commit focus |
| 點擊左側分支名稱 | 標示該分支可追溯到的所有 commit；再點一次取消 |
| 點擊 branch list 空白處 | 取消分支標示 |
| 拖曳畫面 | 平移 graph（滑鼠左鍵拖曳） |
| 拖曳中間分隔線 | 調整 commit detail 面板高度 |
| 工具列「字體」欄位 | 調整介面字體大小，會自動記住 |

## 設定檔

程式會在使用者家目錄下建立以下檔案，用來記住個人化設定（不會被加入 Git 版本控制）：

- `~/.git_graph_viewer_recent.json`：最近開啟過的 repo 路徑
- `~/.git_graph_viewer_fontsize.json`：上次使用的字體大小

## 已知限制

- 透過內建的瀏覽視窗導覽到 `\\wsl$\...` 路徑時，視作業系統與 WSL 版本不同，偶爾仍可能無法正確展開內容，建議直接於路徑欄位手動輸入或貼上完整路徑
- 大型 repository（數千筆以上 commit）尚未特別針對效能優化，載入與互動可能會稍有延遲

## License

依個人需求自由使用、修改。
