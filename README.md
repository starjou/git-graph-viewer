# Git Log Graph Viewer

一個用 Python + PySide6 寫成的輕量級 Git commit graph 圖形化檢視工具。只會執行 `git log` 等**唯讀**指令，不會對你的 repository 做任何寫入或變更操作。

## 功能特色

- **Commit Graph 視覺化**：用顏色區分不同分支線（lane），呈現分叉與合併的關係
- **點擊取得 Focus**：點擊 commit 節點或旁邊的文字列，會高亮該節點，其餘 commit 自動調暗，方便聚焦觀察；點擊空白處可取消 focus
- **Commit 詳細資訊面板**：下方面板顯示完整 hash、作者、日期、parent commit、refs、完整 commit message（含多行內容），文字可選取複製
- **Branch List 依 local/remote 分頁顯示**：左側分支清單上方有 tab bar，`local` 顯示本地分支，其餘每個 remote（如 `origin`）各自一個分頁，互不混雜；點擊分支會把該分支設為主線重新排版（該分支的線固定畫在最左側），標示出其可追溯到的所有 commit，並自動捲動到該分支最新的 commit；再點一次取消，主線恢復為預設分支
- **單一 remote 一鍵 Fetch**：切到某個 remote 分頁時，分頁上會顯示一個 fetch 圖示，點擊只會 `git fetch <該 remote> --prune`，不會動到其他 remote，抓完自動重新整理並停留在同一分頁
- **主線可切換**：Graph 預設以偵測到的預設分支（main/master）為主線繪製，不再單純以「最新 commit」決定哪條線畫在最左側
- **Repositories 選單**：工具列的「Repositories」選單整合了開啟 repo 的所有方式——瀏覽資料夾（Open Repo...）、手動輸入/貼上路徑（Type Path...）、最近開啟清單（Open Recently，項目可 hover 顯示刪除按鈕移除單筆紀錄），以及設定（Settings...，目前提供字體大小）
- **路徑記憶**：開啟過的 repo 路徑會自動記住並正規化正反斜線寫法避免重複紀錄，可從 Open Recently 隨時切換；目前路徑會顯示在唯讀的路徑欄位，旁邊有重新整理與複製路徑按鈕
- **載入中提示**：讀取 repo 時狀態列會顯示 Loading/Fetching 訊息並切換為等待游標，避免不知道程式有沒有在動作
- **WSL 路徑支援**：可直接輸入或透過瀏覽視窗開啟 `\\wsl.localhost\...` / `\\wsl$\...` 這類路徑
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

也可以不帶參數直接執行，啟動後再用工具列的「Repositories」選單開啟資料夾。

```bash
python git_graph_viewer.py C:\path\to\your\repo
```

## 操作說明

| 操作 | 說明 |
|---|---|
| 點擊 commit 節點 / 文字 | 取得 focus，detail panel 顯示完整資訊；再點一次取消 |
| 點擊 graph 空白處 | 取消目前的 commit focus |
| 切換 local/remote 分頁 | 分開檢視本地分支與各 remote 的分支，不互相混雜 |
| 點擊左側分支名稱 | 將該分支設為主線並重新排版、標示其所有 commit，並自動捲動到最新 commit；再點一次取消，主線恢復為預設分支 |
| 點擊 branch list 空白處 | 取消分支標示 |
| 點擊 remote 分頁上的 fetch 圖示 | 只 fetch 該 remote（`git fetch <remote> --prune`），完成後自動重新整理 |
| 拖曳畫面 | 平移 graph（滑鼠左鍵拖曳） |
| 拖曳中間分隔線 | 調整 commit detail 面板高度 |
| 工具列「Repositories」選單 | 開啟 repo（瀏覽/手動輸入路徑）、最近開啟清單、設定（字體大小） |
| 工具列複製按鈕 | 複製目前 repo 路徑到剪貼簿 |

## 設定檔

程式會在使用者家目錄下建立以下檔案，用來記住個人化設定（不會被加入 Git 版本控制）：

- `~/.git_graph_viewer_recent.json`：最近開啟過的 repo 路徑
- `~/.git_graph_viewer_fontsize.json`：上次使用的字體大小

## 已知限制

- 透過內建的瀏覽視窗導覽到 `\\wsl$\...` 路徑時，視作業系統與 WSL 版本不同，偶爾仍可能無法正確展開內容，建議直接於路徑欄位手動輸入或貼上完整路徑
- 大型 repository（數千筆以上 commit）尚未特別針對效能優化，載入與互動可能會稍有延遲
- 本程式在 Windows 上執行，呼叫的是系統 PATH 裡的 Windows 版 `git`（即使開啟的是 `\\wsl.localhost\...` 底下的 repo）。若該 repo 的 remote 只在 WSL 裡 fetch/clone 過，SSH 的 host key 與金鑰只會被信任、記錄在 WSL 那份 `~/.ssh/`，Windows 側的 `C:\Users\<user>\.ssh\` 是空的，點擊 fetch 時可能會遇到 `Host key verification failed` 或 `Permission denied (publickey)`。解法是在 Windows 上也讓該主機的 host key 被信任一次（`ssh -T git@<host>`），並讓 Windows 的 SSH 能用同一把私鑰（可複製一份、用不同檔名並在 `~/.ssh/config` 針對該 host 指定 `IdentityFile`，避免覆蓋掉 Windows 原本的預設金鑰）

## License

本專案採用 MIT License 為基礎，並額外加上「禁止用於收費產品/服務」的限制條款。
可以自由使用、修改、散布（包含修改後僅供個人使用），但不得將本軟體（無論原始或修改後）
販售、收費授權，或包裝進任何收費販售的產品或服務中。詳細條款請見 [LICENSE](LICENSE) 檔案。
