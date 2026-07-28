# Git Log Graph Viewer

一個用 Python + PySide6 寫成的輕量級 Git commit graph 圖形化檢視工具。讀取資料一律使用 `git log` 等**唯讀**指令，**不會**改動你的工作目錄、本地分支或 commit 歷史，也不會切換分支。

唯一會寫入的情況是你主動點擊 remote 分頁上的 fetch 圖示，此時會執行 `git fetch <remote> --prune`，更新遠端追蹤分支（`refs/remotes/...`）；本地分支與工作目錄一樣不受影響。

## 功能特色

- **Commit Graph 視覺化**：用顏色區分不同分支線（lane），呈現分叉與合併的關係。分支線採延遲配置，只有在該分支真正出現 commit 時才佔用一條線，因此即使是分支眾多的共用 repo，畫面也能維持緊湊，不會被大量閒置的線撐開
- **點擊取得 Focus**：點擊 commit 節點或旁邊的文字列，會高亮該節點，其餘 commit 自動調暗，方便聚焦觀察；點擊空白處可取消 focus
- **Commit 詳細資訊面板**：下方面板顯示完整 hash、作者、日期、parent commit、refs、完整 commit message（含多行內容），文字可選取複製
- **Branch List 依 local/remote 分頁顯示**：左側分支清單上方有 tab bar，`local` 顯示本地分支，其餘每個 remote（如 `origin`）各自一個分頁，互不混雜；點擊任一分支即可將它設為主線重新排版，並標示出其可追溯到的所有 commit
- **單一 remote 一鍵 Fetch**：切到某個 remote 分頁時，分頁上會顯示一個 fetch 圖示，點擊只會 `git fetch <該 remote> --prune`，不會動到其他 remote，抓完自動重新整理並停留在同一分頁
- **只看還沒合併的分支**：分頁列右側有一個 `All` 核取方塊，預設不勾選，此時只列出「尚未合併進預設分支」的分支（預設分支本身一律顯示），讓待處理的分支一目了然；勾選後會列出全部分支，其中已合併的會以較暗的顏色標示以便區分
- **主線可切換**：Graph 預設以偵測到的預設分支（main/master）為主線繪製，不再單純以「最新 commit」決定哪條線畫在最左側
- **Repositories 選單**：工具列上開啟 repo 的單一入口，整合了瀏覽資料夾、手動貼上路徑、最近開啟清單與設定
- **路徑記憶**：開啟過的 repo 路徑會自動記住，並正規化正反斜線寫法避免同一路徑重複出現，之後可從 Open Recently 隨時切換，清單中的項目也能逐筆移除
- **載入中提示**：讀取 repo 時狀態列會顯示 Loading/Fetching 訊息並切換為等待游標，避免不知道程式有沒有在動作
- **WSL 路徑支援**：可用 `Type Path...` 貼上或透過瀏覽視窗開啟 `\\wsl.localhost\...` / `\\wsl$\...` 這類路徑
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

帶入路徑參數，啟動時就直接開啟該 repo：

```bash
python git_graph_viewer.py C:\path\to\your\repo
```

也可以不帶參數直接執行，啟動後再用工具列的「Repositories」選單開啟資料夾：

```bash
python git_graph_viewer.py
```

## 操作說明

介面分成三個區域：上方工具列、左側分支面板、右側 graph 與其下方的詳細資訊面板。

### 上方工具列

| 元件 | 說明 |
|---|---|
| **Repositories** 選單 | 開啟 repo 的統一入口，項目見下方表格 |
| 路徑欄位 | 顯示目前開啟的 repo 路徑。唯讀，要換 repo 請走 Repositories 選單 |
| **⟳** | 重新讀取目前 repo 的 commit 與分支清單（例如你剛在別處 commit 完） |
| **📋** | 複製目前 repo 路徑到剪貼簿 |

Repositories 選單的四個項目：

| 項目 | 說明 |
|---|---|
| Open Repo... | 開啟資料夾瀏覽視窗挑選 repo |
| Type Path... | 手動輸入或貼上完整路徑。WSL、網路磁碟機這類路徑建議用這個，比瀏覽視窗可靠 |
| Open Recently | 最近開啟過的 repo 清單，點了直接切換；滑鼠移到某一列時右側會浮現 **✕**，可單獨移除該筆紀錄 |
| Settings... | 目前只有字體大小（7–24 pt），調整後立即套用並記住，下次開啟不必重設 |

### 左側分支面板

| 操作 | 說明 |
|---|---|
| 切換 `local` / remote 分頁 | 分開檢視本地分支與各 remote 的分支，不互相混雜 |
| 勾選 / 取消 `All` | 取消勾選（預設）只列出尚未合併進預設分支的分支；勾選則列出全部，已合併的以較暗顏色標示。預設分支不受影響，一律正常顯示 |
| 點擊分支名稱 | 將該分支設為主線重新排版（它的線固定畫在最左側），標示出其可追溯到的所有 commit，並自動捲動到該分支最新的 commit |
| 再次點擊同一個分支 | 取消標示，主線恢復為預設分支 |
| 點擊清單空白處 | 同上，取消分支標示 |
| 點擊 remote 分頁上的 **⭳** | 只 fetch 該 remote（`git fetch <remote> --prune`），完成後自動重新整理並停留在同一分頁。此圖示只在該分頁被選取時出現 |

### Graph 與詳細資訊面板

| 操作 | 說明 |
|---|---|
| 點擊 commit 節點或右側文字 | 取得 focus，該節點高亮、其餘調暗，下方面板顯示完整 hash、作者、日期、parent、refs 與完整 commit message |
| 再次點擊同一個 commit | 取消 focus |
| 點擊 graph 空白處 | 取消目前的 commit focus |
| 滑鼠停在節點或文字上 | 浮現 tooltip，快速預覽 hash、作者、日期與標題 |
| 左鍵拖曳畫面 | 平移 graph |
| 拖曳 graph 與下方面板之間的分隔線 | 調整詳細資訊面板高度 |
| 在詳細資訊面板中選取文字 | 可直接複製，方便取用完整 hash 或 commit message |

## 設定檔

程式會在使用者家目錄下建立以下檔案，用來記住個人化設定（不會被加入 Git 版本控制）：

- `~/.git_graph_viewer_recent.json`：最近開啟過的 repo 路徑
- `~/.git_graph_viewer_fontsize.json`：上次使用的字體大小

## 已知限制

- 透過 `Open Repo...` 的瀏覽視窗導覽到 `\\wsl$\...` 路徑時，視作業系統與 WSL 版本不同，偶爾仍可能無法正確展開內容，建議改用 `Type Path...` 直接貼上完整路徑
- 大型 repository（數千筆以上 commit）尚未特別針對效能優化，載入與互動可能會稍有延遲
- 本程式在 Windows 上執行，呼叫的是系統 PATH 裡的 Windows 版 `git`（即使開啟的是 `\\wsl.localhost\...` 底下的 repo）。若該 repo 的 remote 只在 WSL 裡 fetch/clone 過，SSH 的 host key 與金鑰只會被信任、記錄在 WSL 那份 `~/.ssh/`，Windows 側的 `C:\Users\<user>\.ssh\` 是空的，點擊 fetch 時可能會遇到 `Host key verification failed` 或 `Permission denied (publickey)`。解法是在 Windows 上也讓該主機的 host key 被信任一次（`ssh -T git@<host>`），並讓 Windows 的 SSH 能用同一把私鑰（可複製一份、用不同檔名並在 `~/.ssh/config` 針對該 host 指定 `IdentityFile`，避免覆蓋掉 Windows 原本的預設金鑰）

## License

本專案採用 MIT License 為基礎，並額外加上「禁止用於收費產品/服務」的限制條款。
可以自由使用、修改、散布（包含修改後僅供個人使用），但不得將本軟體（無論原始或修改後）
販售、收費授權，或包裝進任何收費販售的產品或服務中。詳細條款請見 [LICENSE](LICENSE) 檔案。
