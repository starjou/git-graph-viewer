#!/usr/bin/env python3
"""
Git Log Graph Viewer
只讀取 git log,不執行任何寫入/變更類的 git 指令。
依賴: PySide6  (pip install PySide6 --break-system-packages)
用法: python git_graph_viewer.py [repo_path]
"""

import sys
import os
import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsScene, QGraphicsView,
    QFileDialog, QToolBar, QLineEdit, QLabel, QGraphicsEllipseItem,
    QGraphicsLineItem, QGraphicsTextItem, QGraphicsPathItem, QGraphicsRectItem,
    QMessageBox, QStatusBar, QDockWidget, QListWidget, QListWidgetItem,
    QTextEdit, QSplitter, QSpinBox, QToolButton, QMenu, QDialog, QFormLayout,
    QInputDialog, QTabBar, QWidget, QVBoxLayout, QHBoxLayout, QWidgetAction,
    QCheckBox
)
from PySide6.QtGui import QColor, QPen, QBrush, QFont, QPainterPath, QAction
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer


# ----------------------------------------------------------------------
# subprocess 呼叫共用參數：避免用 pythonw 啟動時，每次呼叫 git 都跳出一個
# 新的 cmd 視窗（Windows 專屬行為，其他平台無影響）。
# ----------------------------------------------------------------------
_SUBPROCESS_NO_WINDOW = {}
if sys.platform == "win32":
    _SUBPROCESS_NO_WINDOW["creationflags"] = subprocess.CREATE_NO_WINDOW


def run_git(cmd, **kwargs):
    """subprocess.run 的包裝：統一補上不開視窗參數，其餘用法與 subprocess.run 相同。"""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return subprocess.run(cmd, **_SUBPROCESS_NO_WINDOW, **kwargs)


# ----------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------

@dataclass
class Commit:
    chash: str
    parents: list
    subject: str
    author: str
    date: str
    refs: str
    body: str = ""
    row: int = 0
    lane: int = 0


SEP = "\x1f"  # unit separator, unlikely to appear in commit text
REC_SEP = "\x1e"  # record separator


def load_commits(repo_path: str, branch_scope: str = "--all", limit: Optional[int] = None) -> list:
    """執行 git log 並回傳 Commit 物件清單(由新到舊,topological 順序)。"""
    fmt = f"%H{SEP}%P{SEP}%s{SEP}%an{SEP}%ad{SEP}%D{SEP}%b{REC_SEP}"
    cmd = [
        "git", "-C", repo_path, "log",
        branch_scope,
        "--date=short",
        f"--pretty=format:{fmt}",
        "--topo-order",
    ]
    if limit:
        cmd.insert(4, f"-{limit}")

    result = run_git(cmd, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git log 執行失敗")
    if result.stdout is None:
        raise RuntimeError(f"git 沒有任何輸出 (stderr: {result.stderr!r})")

    commits = []
    raw = result.stdout.split(REC_SEP)
    for rec in raw:
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        parts = rec.split(SEP)
        if len(parts) < 7:
            continue
        chash, parents_raw, subject, author, date, refs, body = parts[:7]
        parents = parents_raw.split() if parents_raw.strip() else []
        commits.append(Commit(
            chash=chash, parents=parents, subject=subject,
            author=author, date=date, refs=refs.strip(), body=body.strip()
        ))
    return commits


# ----------------------------------------------------------------------
# Lane / layout algorithm (similar to how `git log --graph` lays things out)
# ----------------------------------------------------------------------

LANE_COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#46f0f0", "#f032e6", "#bcf60c", "#fabebe", "#008080",
    "#e6beff", "#9a6324", "#800000", "#aaffc3", "#808000",
]


def _nearest_free_lane(active_lanes: list, anchor: Optional[int]) -> Optional[int]:
    """在 active_lanes 裡找一個空的 lane index，優先挑離 anchor 最近的；
    anchor 是 None 時退化成「第一個找到的空 lane」。找不到回傳 None（呼叫端自行 append）。"""
    best_i = None
    best_dist = None
    for i, expected in enumerate(active_lanes):
        if expected is None:
            dist = abs(i - anchor) if anchor is not None else i
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_i = i
    return best_i


def compute_layout(commits: list, mainline_tip_hash: Optional[str] = None):
    """為每個 commit 指定 (row, lane),回傳 commits 以及 edges 清單。
    edges: list of (parent_hash, child_hash, lane_color_index)

    mainline_tip_hash: 若指定，會先把 lane 0 保留給這個 commit，讓它沿著
    first-parent chain 一路占住 lane 0，其餘分支自動被推到別的 lane。
    不指定時維持舊行為：誰在 commits 清單裡最先出現（也就是最新的
    commit）就先搶到 lane 0。
    """
    hash_to_commit = {c.chash: c for c in commits}
    if mainline_tip_hash and mainline_tip_hash in hash_to_commit:
        active_lanes: list = [mainline_tip_hash]  # 預先保留 lane 0 給主線分支
    else:
        active_lanes = []  # each slot: expected commit hash or None
    edges = []
    # merge 的第二個 parent 先不佔 lane，只記在這裡：hash -> 期望靠近的 lane index。
    # 等 topo-order 真的走到那個 commit 時，才拿這個提示去挑最近的空 lane。
    pending_hint: dict = {}

    for row, c in enumerate(commits):
        c.row = row

        # find a lane reserved for this commit
        lane_idx = None
        for i, expected in enumerate(active_lanes):
            if expected == c.chash:
                lane_idx = i
                break
        if lane_idx is None:
            # 沒有任何 lane 在等這個 commit，需要現場分配一條。
            # 若之前某個 merge 替它留過提示（它是那個 merge 的第二個 parent），
            # 就挑離提示最近的空 lane，讓它盡量長在合併對象旁邊。
            anchor = pending_hint.pop(c.chash, None)
            lane_idx = _nearest_free_lane(active_lanes, anchor)
            if lane_idx is None:
                lane_idx = len(active_lanes)
                active_lanes.append(None)
        else:
            pending_hint.pop(c.chash, None)  # 已經有 lane 在等它了，提示用不到

        c.lane = lane_idx

        # clear any *other* lanes that were also waiting for this same hash
        # (two children of the same fork point can both reserve it)
        for i, expected in enumerate(active_lanes):
            if expected == c.chash and i != lane_idx:
                active_lanes[i] = None

        parents = c.parents
        if not parents:
            active_lanes[lane_idx] = None
        else:
            # first parent continues in the same lane
            active_lanes[lane_idx] = parents[0]
            edges.append((parents[0], c.chash, lane_idx))
            # additional parents (merges)
            for p in parents[1:]:
                # 如果這個 parent 已經有別的 active lane 在等它了（例如它是條長期
                # 存活、目前仍持續前進的分支，如 develop），就不要再另外硬塞一個
                # 新 lane 蓋過去——那樣只會製造一筆多餘的重複保留，之後真正處理到
                # 這個 commit 時，兩筆保留其中一筆會被清掉，很可能反而把它原本
                # 正確的 lane 位置洗掉、變成畫在別的地方。直接沿用既有的 lane 即可。
                existing_lane = None
                for i, expected in enumerate(active_lanes):
                    if expected == p:
                        existing_lane = i
                        break
                if existing_lane is not None:
                    edges.append((p, c.chash, existing_lane))
                    continue
                # 沒有既有保留時，這裡「不」立刻替它佔一條 lane。
                # 在 topo-order 下，這個 parent 往往排在很後面（可能差上百 row），
                # 若現在就預訂，那條 lane 從預訂到真正被使用之間會長期閒置又不能
                # 釋放，lane index 就被一路往右 append，畫出橫跨整張圖的大弧線。
                # 改成只留一個「將來請長在這附近」的提示，等真的走到它再分配。
                pending_hint.setdefault(p, lane_idx)
                # edge 的位置只由 child.lane / parent.lane 決定，這裡的 lane index
                # 僅用來選線的顏色，沿用 merge commit 自己的 lane 即可。
                edges.append((p, c.chash, lane_idx))

    return commits, edges, hash_to_commit


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------

ROW_HEIGHT = 34
LANE_WIDTH = 22
NODE_RADIUS = 5
LEFT_MARGIN = 20
TEXT_X_PAD = 16

NODE_PEN_NORMAL = QPen(QColor("#1e1e1e"), 1)
NODE_PEN_FOCUSED = QPen(QColor("#ffffff"), 2.5)
DIM_OPACITY = 0.32
HIGHLIGHT_BG = QColor(255, 255, 255, 28)
HIGHLIGHT_BORDER = QColor("#ffffff")


class CommitNodeItem(QGraphicsEllipseItem):
    """可點擊的 commit 節點，點擊會通知 view 切換 focus 狀態。"""

    def __init__(self, x, y, r, commit_hash, view_ref):
        super().__init__(x - r, y - r, r * 2, r * 2)
        self.commit_hash = commit_hash
        self.view_ref = view_ref
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        self.view_ref.toggle_focus(self.commit_hash)
        super().mousePressEvent(event)


class CommitTextItem(QGraphicsTextItem):
    """可點擊的 commit 文字列，點擊行為與節點相同（共用 toggle_focus），
    方便瞄準有困難時改點文字也能取得 focus。"""

    def __init__(self, commit_hash, view_ref):
        super().__init__()
        self.commit_hash = commit_hash
        self.view_ref = view_ref
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptHoverEvents(True)
        # 預設 QGraphicsTextItem 若開啟 TextInteraction 會搶走點擊事件去做文字選取，
        # 這裡保持不可選取文字、單純當成可點擊區塊
        self.setTextInteractionFlags(Qt.NoTextInteraction)

    def mousePressEvent(self, event):
        self.view_ref.toggle_focus(self.commit_hash)
        super().mousePressEvent(event)


def branch_label_html(refs: str) -> str:
    """把 git 的 refs 字串轉成有顏色/粗體的 HTML 片段，只保留本地分支，過濾遠端(origin/remotes)。"""
    if not refs:
        return ""
    names = [r.strip() for r in refs.split(",") if r.strip()]
    spans = []
    for n in names:
        n = n.replace("HEAD -> ", "")
        if not n or n.startswith("origin/") or n.startswith("remotes/") or n.startswith("tag:"):
            continue
        spans.append(f'<b><span style="color:#8be28b;">[{n}]</span></b>')
    return " ".join(spans)


def get_default_branch_name(repo_path: str, available: list) -> Optional[str]:
    """偵測 repo 的預設分支名稱。優先採用遠端 origin 設定的 HEAD 指向，
    抓不到時退而求其次找常見命名（main / master）。"""
    result = run_git(
        ["git", "-C", repo_path, "symbolic-ref", "refs/remotes/origin/HEAD"],
        encoding="utf-8", errors="replace"
    )
    if result.returncode == 0:
        ref = result.stdout.strip()
        prefix = "refs/remotes/origin/"
        if ref.startswith(prefix):
            name = ref[len(prefix):]
            if name in available:
                return name
    for fallback in ("main", "master"):
        if fallback in available:
            return fallback
    return None


def local_branch_names(repo_path: str) -> list:
    """取得本地分支名稱清單，預設分支（main/master 或 origin HEAD 指向的分支）排在最前面。"""
    result = run_git(
        ["git", "-C", repo_path, "branch", "--format=%(refname:short)"],
        encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        return []
    names = [b.strip() for b in result.stdout.splitlines() if b.strip()]

    default_name = get_default_branch_name(repo_path, names)
    if default_name and default_name in names:
        names.remove(default_name)
        names.insert(0, default_name)
    return names


def list_remote_names(repo_path: str) -> list:
    """取得這個 repo 設定的所有 remote 名稱（如 origin、hub）。"""
    result = run_git(
        ["git", "-C", repo_path, "remote"],
        encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        return []
    return [r.strip() for r in result.stdout.splitlines() if r.strip()]


def remote_branch_names(repo_path: str, remote: str) -> list:
    """取得某個 remote 底下的分支名稱清單（不含 remote 前綴，也濾掉 HEAD 指標）。"""
    result = run_git(
        ["git", "-C", repo_path, "for-each-ref", "--format=%(refname:short)", f"refs/remotes/{remote}"],
        encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        return []
    prefix = f"{remote}/"
    names = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line == f"{remote}/HEAD":
            continue
        if line.startswith(prefix):
            names.append(line[len(prefix):])
    return names


def merged_ref_names(repo_path: str, target_branch: str) -> set:
    """取得（本地 + 各 remote）已經合併進 target_branch 的分支 short name 集合，
    用來判斷 branch list 裡哪些項目已經合併過。"""
    result = run_git(
        ["git", "-C", repo_path, "branch", "--all", "--merged", target_branch,
         "--format=%(refname:short)"],
        encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        return set()
    return set(line.strip() for line in result.stdout.splitlines() if line.strip())


def branch_tip_hash(repo_path: str, branch_name: str) -> Optional[str]:
    """取得某分支 tip 的 commit hash，用來當作主線繪圖的起點。"""
    result = run_git(
        ["git", "-C", repo_path, "rev-parse", branch_name],
        encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def branch_ancestor_hashes(repo_path: str, branch_name: str) -> set:
    """取得某分支可追溯到的所有 commit hash 集合（用於高亮標示）。"""
    result = run_git(
        ["git", "-C", repo_path, "log", branch_name, "--pretty=%H"],
        encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        return set()
    return set(h.strip() for h in result.stdout.splitlines() if h.strip())


NODE_PEN_BRANCH_HILITE = QPen(QColor("#ffd54a"), 2.2)


class GitGraphView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.scene_ = QGraphicsScene()
        self.setScene(self.scene_)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 內容固定貼齊左上角，避免視窗放大時內容被置中、左側留白
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setResizeAnchor(QGraphicsView.NoAnchor)

        self.commit_items: dict = {}   # hash -> {node, text, highlight}
        self.hash_to_commit: dict = {}
        self.focused_hash: Optional[str] = None
        self.branch_highlight_hashes: Optional[set] = None
        self.detail_panel: Optional[QTextEdit] = None  # 由 MainWindow 注入
        self._press_pos = None
        self.font_size = 9  # 可由 MainWindow 的字體大小控制調整

    def mousePressEvent(self, event):
        self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._press_pos is not None:
            moved = (event.position().toPoint() - self._press_pos).manhattanLength()
            if moved < 4:  # 視為「點擊」而非拖曳平移
                item = self.itemAt(event.position().toPoint())
                if not isinstance(item, (CommitNodeItem, CommitTextItem)) and self.focused_hash is not None:
                    self.focused_hash = None
                    self.apply_focus_style()
                    self._update_detail_panel()
        self._press_pos = None

    def set_detail_panel(self, panel: QTextEdit):
        self.detail_panel = panel

    def scroll_to_commit(self, commit_hash: str):
        """把畫面捲動到指定 commit 節點所在位置（置中顯示）。"""
        items = self.commit_items.get(commit_hash)
        if items:
            self.centerOn(items["node"])

    def clear(self):
        self.scene_.clear()
        self.commit_items = {}
        self.hash_to_commit = {}
        self.focused_hash = None
        self.branch_highlight_hashes = None

    def toggle_focus(self, commit_hash: str):
        # 點擊 commit 節點時，視為切換到「單一 commit focus」模式，取消分支高亮模式
        self.branch_highlight_hashes = None
        self.focused_hash = None if self.focused_hash == commit_hash else commit_hash
        self.apply_focus_style()
        self._update_detail_panel()

    def set_branch_highlight(self, hashes: set):
        # 選擇分支時，視為切換到「分支高亮」模式，取消單一 commit focus
        self.focused_hash = None
        self.branch_highlight_hashes = hashes
        self.apply_focus_style()
        self._update_detail_panel()

    def clear_branch_highlight(self):
        self.branch_highlight_hashes = None
        self.apply_focus_style()
        self._update_detail_panel()

    def _update_detail_panel(self):
        if self.detail_panel is None:
            return
        if self.focused_hash and self.focused_hash in self.hash_to_commit:
            c = self.hash_to_commit[self.focused_hash]
            text = (
                f"Hash: {c.chash}\n"
                f"Author: {c.author}\n"
                f"Date: {c.date}\n"
                f"Parents: {', '.join(p[:10] for p in c.parents) or '(none)'}\n"
                f"Refs: {c.refs or '(none)'}\n"
                f"\n{c.subject}"
            )
            if c.body:
                text += f"\n\n{c.body}"
            self.detail_panel.setPlainText(text)
        else:
            self.detail_panel.setPlainText("")

    def apply_focus_style(self):
        has_commit_focus = self.focused_hash is not None
        has_branch_focus = self.branch_highlight_hashes is not None
        for h, items in self.commit_items.items():
            node = items["node"]
            text = items["text"]
            highlight = items["highlight"]

            if has_commit_focus:
                is_focused = (h == self.focused_hash)
                node.setPen(NODE_PEN_FOCUSED if is_focused else NODE_PEN_NORMAL)
                text.setOpacity(1.0 if is_focused else DIM_OPACITY)
                highlight.setVisible(is_focused)
            elif has_branch_focus:
                in_branch = h in self.branch_highlight_hashes
                node.setPen(NODE_PEN_BRANCH_HILITE if in_branch else NODE_PEN_NORMAL)
                text.setOpacity(1.0 if in_branch else DIM_OPACITY)
                highlight.setVisible(False)
            else:
                node.setPen(NODE_PEN_NORMAL)
                text.setOpacity(1.0)
                highlight.setVisible(False)

    def render_commits(self, commits, edges, hash_to_commit, max_lanes):
        self.clear()
        self.hash_to_commit = hash_to_commit
        font = QFont("Consolas", self.font_size)
        row_height = max(24, int(self.font_size * 3.6))  # 字體變大時，行距跟著放大避免重疊
        node_radius = max(4, int(self.font_size * 0.6))
        graph_width = LEFT_MARGIN + (max_lanes + 1) * LANE_WIDTH

        # 先畫連線，節點才會疊在上面
        for parent_hash, child_hash, lane_idx in edges:
            parent = hash_to_commit.get(parent_hash)
            child = hash_to_commit.get(child_hash)
            if not parent or not child:
                continue
            x1 = LEFT_MARGIN + child.lane * LANE_WIDTH
            y1 = child.row * row_height + row_height / 2
            x2 = LEFT_MARGIN + parent.lane * LANE_WIDTH
            y2 = parent.row * row_height + row_height / 2

            color = QColor(LANE_COLORS[lane_idx % len(LANE_COLORS)])
            pen = QPen(color, 2)
            pen.setCosmetic(True)

            path = QPainterPath(QPointF(x1, y1))
            if x1 == x2:
                path.lineTo(x2, y2)
            else:
                mid_y = y1 + (y2 - y1) * 0.5
                path.cubicTo(QPointF(x1, mid_y), QPointF(x2, mid_y), QPointF(x2, y2))
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            self.scene_.addItem(item)

        # 節點 + 簡化文字 (title + branch name)
        for c in commits:
            x = LEFT_MARGIN + c.lane * LANE_WIDTH
            y = c.row * row_height + row_height / 2
            color = QColor(LANE_COLORS[c.lane % len(LANE_COLORS)])

            tooltip = (
                f"{c.chash[:10]}\n{c.author}, {c.date}\n{c.subject}"
                + (f"\nrefs: {c.refs}" if c.refs else "")
            )

            node = CommitNodeItem(x, y, node_radius, c.chash, self)
            node.setBrush(QBrush(color))
            node.setPen(NODE_PEN_NORMAL)
            node.setToolTip(tooltip)
            self.scene_.addItem(node)

            branch_html = branch_label_html(c.refs)
            title_text = c.subject.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html = f'<span style="color:#dddddd;">{c.chash[:7]}&nbsp; {title_text}</span>'
            if branch_html:
                html += f"&nbsp;&nbsp;{branch_html}"

            text_x = graph_width + TEXT_X_PAD
            text_y = c.row * row_height + 2

            text = CommitTextItem(c.chash, self)
            text.setHtml(html)
            text.setFont(font)
            text.setToolTip(tooltip)
            text.setPos(text_x, text_y)
            text.setTextWidth(-1)  # 不換行，讓場景寬度自然撐開以利水平捲動

            text_width = text.boundingRect().width()
            highlight = QGraphicsRectItem(
                text_x - 4, text_y - 1, text_width + 8, row_height - 4
            )
            highlight.setBrush(QBrush(HIGHLIGHT_BG))
            highlight.setPen(QPen(HIGHLIGHT_BORDER, 1))
            highlight.setVisible(False)
            highlight.setZValue(-1)

            self.scene_.addItem(highlight)
            self.scene_.addItem(text)

            self.commit_items[c.chash] = {"node": node, "text": text, "highlight": highlight}

        # 用實際內容的 bounding rect 設定場景大小，確保水平/垂直 scrollbar 抓得到正確範圍
        bounds = self.scene_.itemsBoundingRect()
        padding = 40
        self.scene_.setSceneRect(
            bounds.left() - padding,
            bounds.top() - padding,
            bounds.width() + padding * 2,
            bounds.height() + padding * 2,
        )


import traceback


def show_error_dialog(parent, title: str, message: str):
    """獨立建立錯誤視窗，直接在 instance 上設定樣式，避免被父視窗的深色樣式表繼承影響。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(title)
    box.setText(message)
    box.setStyleSheet(
        "QMessageBox { background-color: #f5f5f5; }"
        "QLabel { color: #000000; background-color: transparent; }"
        "QPushButton { color: #000000; background-color: #e0e0e0; padding: 4px 14px; }"
    )
    box.exec()


def show_question_dialog(parent, title: str, message: str) -> bool:
    """獨立建立 Yes/No 詢問視窗，回傳使用者是否選擇「是」。"""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(message)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.Yes)
    box.setStyleSheet(
        "QMessageBox { background-color: #f5f5f5; }"
        "QLabel { color: #000000; background-color: transparent; }"
        "QPushButton { color: #000000; background-color: #e0e0e0; padding: 4px 14px; }"
    )
    return box.exec() == QMessageBox.Yes


RECENT_PATHS_FILE = os.path.join(os.path.expanduser("~"), ".git_graph_viewer_recent.json")
MAX_RECENT_PATHS = 10
FONT_SIZE_FILE = os.path.join(os.path.expanduser("~"), ".git_graph_viewer_fontsize.json")
DEFAULT_FONT_SIZE = 9


def load_font_size() -> int:
    try:
        with open(FONT_SIZE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            value = int(data.get("font_size", DEFAULT_FONT_SIZE))
            return max(7, min(24, value))  # 夾在 spinbox 允許的範圍內，避免設定檔被改壞
    except Exception:
        return DEFAULT_FONT_SIZE


def save_font_size(value: int):
    try:
        with open(FONT_SIZE_FILE, "w", encoding="utf-8") as f:
            json.dump({"font_size": value}, f)
    except Exception:
        pass  # 存檔失敗不影響主功能，安靜略過即可


def normalize_path(path: str) -> str:
    """統一路徑寫法（正斜線/反斜線、多餘分隔符號等），讓瀏覽器選的跟手動輸入的
    只要指向同一個地方，就會被視為同一筆紀錄，不會在歷史清單裡重複出現。"""
    try:
        return os.path.normpath(path)
    except Exception:
        return path


def load_recent_paths() -> list:
    try:
        with open(RECENT_PATHS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                raw = [p for p in data if isinstance(p, str)]
                # 正規化並去重（保留先出現的順序），順便清掉舊資料裡因為正反斜線
                # 不一致造成的重複項目
                seen = set()
                result = []
                for p in raw:
                    norm = normalize_path(p)
                    if norm not in seen:
                        seen.add(norm)
                        result.append(norm)
                return result
    except Exception:
        pass
    return []


def save_recent_paths(paths: list):
    try:
        with open(RECENT_PATHS_FILE, "w", encoding="utf-8") as f:
            json.dump(paths[:MAX_RECENT_PATHS], f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 存檔失敗不影響主功能，安靜略過即可


class BranchListWidget(QListWidget):
    """點擊清單中沒有項目的空白區域時會發出 emptyClicked 訊號。"""
    emptyClicked = Signal()

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        super().mousePressEvent(event)
        if item is None:
            self.emptyClicked.emit()


class RecentPathRow(QWidget):
    """Open Recently 選單裡的一列：滑鼠移過去時右邊會浮現刪除按鈕，
    點列本身（刪除按鈕以外的地方）會開啟該路徑。"""
    open_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(6)

        label = QLabel(path)
        label.setStyleSheet("color: #ffffff;")
        layout.addWidget(label, 1)

        self.delete_btn = QToolButton()
        self.delete_btn.setText("✕")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setToolTip("Remove")
        self.delete_btn.setStyleSheet(
            "QToolButton { color: #cc7777; border: none; padding: 0px 4px; }"
            "QToolButton:hover { color: #ff5555; }"
        )
        self.delete_btn.setVisible(False)
        self.delete_btn.clicked.connect(lambda: self.remove_requested.emit(self.path))
        layout.addWidget(self.delete_btn)

    def enterEvent(self, event):
        self.delete_btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.delete_btn.setVisible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if not self.delete_btn.underMouse():
            self.open_requested.emit(self.path)
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, repo_path: Optional[str] = None):
        super().__init__()
        self.setWindowTitle("Git Log Graph Viewer")
        self.resize(1300, 800)
        self.setStyleSheet("background-color: #2b2b2b;")

        self.view = GitGraphView()
        self.view.setStyleSheet("background-color: #2b2b2b; border: none;")

        # 下方 commit detail 面板，文字可選取/複製
        self.detail_panel = QTextEdit()
        self.detail_panel.setReadOnly(True)
        self.detail_panel.setPlaceholderText("點擊一個 commit 節點查看詳細資訊...")
        self.detail_panel.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #dddddd; "
            "font-family: Consolas; font-size: 10pt; border: none; padding: 8px; }"
        )
        # 不設 setMaximumHeight，讓使用者可以自由拖曳 splitter 把面板拉高，
        # 初始高度仍由下方 splitter.setSizes() 控制為 140px
        self.view.set_detail_panel(self.detail_panel)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.view)
        splitter.addWidget(self.detail_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setChildrenCollapsible(False)
        # 明確指定初始大小分配：graph 區域盡量大、detail panel 給固定的合理高度，
        # 避免剛開窗時 splitter 用 sizeHint 自動估算導致下方留白
        splitter.setSizes([10000, 140])
        self.setCentralWidget(splitter)
        self._splitter = splitter

        # 左側 branch list，上面加一個 tab bar 依 local/remote 分開顯示
        self.branch_tab_bar = QTabBar()
        self.branch_tab_bar.setStyleSheet(
            "QTabBar { background-color: #2b2b2b; }"
            "QTabBar::tab { background-color: #2b2b2b; color: #aaaaaa; "
            "padding: 6px 14px; }"
            "QTabBar::tab:selected { background-color: #3a3a3a; color: #ffffff; }"
            "QTabBar::tab:hover { color: #ffffff; }"
        )
        self.branch_tab_bar.currentChanged.connect(self._on_branch_tab_changed)
        self.branch_tab_order: list = []          # tab index -> tab key（"local" 或 remote 名稱）
        self.branch_tab_data: dict = {}           # tab key -> [(display_name, full_ref_name), ...]

        self.branch_list = BranchListWidget()
        self.branch_list.setStyleSheet(
            "QListWidget { background-color: #2b2b2b; color: #dddddd; border: none; }"
            "QListWidget::item { padding: 4px 8px; }"
            "QListWidget::item:selected { background-color: #ffd54a; color: #000000; }"
        )
        self.branch_list.itemClicked.connect(self.on_branch_clicked)
        self.branch_list.emptyClicked.connect(self.clear_branch_selection)
        self.selected_branch_name: Optional[str] = None
        self.default_branch_name: Optional[str] = None  # main/master，重設主線時的預設值
        self.mainline_branch: Optional[str] = None       # 目前畫圖用的主線分支
        self.raw_commits: Optional[list] = None          # compute_layout 前的原始 commit 清單，換主線時免重讀 git log
        self.merged_ref_names: set = set()               # 已合併進預設分支的 branch short name 集合

        self.show_all_checkbox = QCheckBox("All")
        self.show_all_checkbox.setStyleSheet(
            "QCheckBox { color: #aaaaaa; padding: 0px 10px; background-color: #2b2b2b; }"
        )
        self.show_all_checkbox.stateChanged.connect(self._on_show_all_toggled)
        self.show_all_checkbox.setVisible(False)  # 還沒載入 repo 時不顯示

        tab_row = QWidget()
        tab_row.setStyleSheet("background-color: #2b2b2b;")
        tab_row_layout = QHBoxLayout(tab_row)
        tab_row_layout.setContentsMargins(0, 0, 0, 0)
        tab_row_layout.setSpacing(0)
        tab_row_layout.addWidget(self.branch_tab_bar, 1)
        tab_row_layout.addWidget(self.show_all_checkbox)

        branch_panel = QWidget()
        branch_panel_layout = QVBoxLayout(branch_panel)
        branch_panel_layout.setContentsMargins(0, 0, 0, 0)
        branch_panel_layout.setSpacing(0)
        branch_panel_layout.addWidget(tab_row)
        branch_panel_layout.addWidget(self.branch_list)

        branch_dock = QDockWidget("Branches", self)
        branch_dock.setWidget(branch_panel)
        # 固定停靠，不可拖曳浮動、不可關閉，避開 Qt6 浮動視窗的邊角問題
        branch_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        # 移除標題列（含拖曳/浮動/關閉按鈕），改用一個空白 widget 取代，
        # 等同完全拿掉那條 title bar
        branch_dock.setTitleBarWidget(QLabel(""))
        branch_dock.setStyleSheet(
            "QDockWidget { color: #dddddd; background-color: #2b2b2b; }"
        )
        self.addDockWidget(Qt.LeftDockWidgetArea, branch_dock)
        self.branch_dock = branch_dock

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet(
            "QToolBar { padding: 4px; spacing: 6px; }"
            "QToolButton { padding: 5px 12px; border-radius: 3px; color: #ffffff; }"
            "QToolButton:hover { background-color: #4a4a4a; }"
            "QToolButton:pressed { background-color: #555555; }"
        )
        self.addToolBar(toolbar)

        menu_button = QToolButton()
        menu_button.setText("Repositories")
        menu_button.setPopupMode(QToolButton.InstantPopup)
        menu_button.setCursor(Qt.PointingHandCursor)
        menu_button.setStyleSheet(
            "QToolButton::menu-indicator { image: none; width: 0px; }"
        )

        main_menu = QMenu(menu_button)
        self.main_menu = main_menu
        main_menu.setStyleSheet(
            "QMenu { background-color: #2b2b2b; color: #ffffff; border: 1px solid #555; }"
            "QMenu::item:selected { background-color: #3a6ea5; }"
            "QMenu::item:disabled { color: #888888; }"
        )

        open_action = QAction("Open Repo...", self)
        open_action.triggered.connect(self.open_repo_dialog)
        main_menu.addAction(open_action)

        type_path_action = QAction("Type Path...", self)
        type_path_action.triggered.connect(self.open_type_path_dialog)
        main_menu.addAction(type_path_action)

        self.recent_menu = QMenu("Open Recently", main_menu)
        self.recent_menu.setStyleSheet(main_menu.styleSheet())
        main_menu.addMenu(self.recent_menu)
        self._refresh_recent_menu()

        main_menu.addSeparator()

        settings_action = QAction("Settings...", self)
        settings_action.triggered.connect(self.open_settings_dialog)
        main_menu.addAction(settings_action)

        menu_button.setMenu(main_menu)
        toolbar.addWidget(menu_button)

        self.path_display = QLineEdit()
        self.path_display.setReadOnly(True)
        self.path_display.setMinimumWidth(420)
        self.path_display.setStyleSheet(
            "QLineEdit { background-color: #1e1e1e; color: #cccccc; "
            "border: 1px solid #555; padding: 2px 4px; }"
        )
        toolbar.addWidget(self.path_display)

        refresh_button = QToolButton()
        refresh_button.setText("⟳")
        refresh_button.setToolTip("重新整理")
        refresh_button.setCursor(Qt.PointingHandCursor)
        refresh_button.setFixedSize(32, 32)
        refresh_button.setStyleSheet(
            "QToolButton { font-size: 18pt; padding: 0px 0px 6px 0px; }"
        )
        refresh_button.clicked.connect(lambda: self.refresh())
        toolbar.addWidget(refresh_button)

        copy_button = QToolButton()
        copy_button.setText("📋")
        copy_button.setToolTip("Copy Path")
        copy_button.setCursor(Qt.PointingHandCursor)
        copy_button.setFixedSize(32, 32)
        copy_button.setStyleSheet(
            "QToolButton { font-size: 14pt; padding: 0px; }"
        )
        copy_button.clicked.connect(self.copy_path_to_clipboard)
        toolbar.addWidget(copy_button)

        self.last_render_data = None  # (commits, edges, hash_to_commit, max_lanes)，供調整字體時免重新讀 git log
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(7, 24)
        self.font_size_spin.setValue(load_font_size())  # 讀取上次記住的字體大小
        self.font_size_spin.setStyleSheet(
            "QSpinBox { background-color: #1e1e1e; color: #ffffff; "
            "border: 1px solid #555; padding: 2px 4px; }"
        )
        self.font_size_spin.valueChanged.connect(self.on_font_size_changed)
        self.on_font_size_changed(self.font_size_spin.value())  # 套用到 view 上（此時還沒有 commit 資料，安全）
        self._build_settings_dialog()

        self.repo_path = repo_path
        if repo_path:
            self.path_display.setText(repo_path)
            self.refresh(repo_path)

    def showEvent(self, event):
        super().showEvent(event)
        # 視窗幾何尺寸確定顯示後，再套用一次，避免初次開窗時 splitter 計算錯誤留白
        QTimer.singleShot(0, lambda: self._splitter.setSizes([10000, 140]))

    def open_repo_dialog(self):
        # 用「手動建構 QFileDialog + exec()」而非靜態便利函式 getExistingDirectory()，
        # 在 Windows 上才會是新版原生對話框（頂端有地址列可直接打字貼路徑，
        # 也才能正確認得 \\wsl$ 這類路徑）。
        dlg = QFileDialog(self, "選擇 Git Repository 資料夾")
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.ShowDirsOnly, True)
        if dlg.exec():
            selected = dlg.selectedFiles()
            if selected:
                self._open_path(selected[0])

    def open_type_path_dialog(self):
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Type Path")
        dlg.setLabelText("Repository path:")
        dlg.setTextValue(self.repo_path or "")
        dlg.resize(560, dlg.height())
        dlg.setStyleSheet(
            "QDialog { background-color: #2b2b2b; }"
            "QLabel { color: #ffffff; }"
            "QLineEdit { background-color: #1e1e1e; color: #ffffff; "
            "border: 1px solid #555; padding: 4px; }"
            "QPushButton { background-color: #3a3a3a; color: #ffffff; "
            "border: 1px solid #555; padding: 4px 14px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #4a4a4a; }"
        )
        if dlg.exec() and dlg.textValue().strip():
            self._open_path(dlg.textValue().strip())

    def _open_path(self, path: str):
        self.path_display.setText(path)
        self.refresh(path)

    def copy_path_to_clipboard(self):
        if self.repo_path:
            QApplication.clipboard().setText(self.repo_path)
            self.status.showMessage("Path copied to clipboard")

    def fetch_remote(self, remote: str):
        if not self.repo_path:
            return
        button = self.sender()
        if isinstance(button, QToolButton):
            button.setEnabled(False)
        self.status.showMessage(f"Fetching {remote}...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            result = run_git(
                ["git", "-C", self.repo_path, "fetch", remote, "--prune"],
                encoding="utf-8", errors="replace"
            )
            if result.returncode != 0:
                show_error_dialog(self, f"Fetch {remote} failed", result.stderr.strip() or "git fetch 執行失敗")
                self.status.showMessage(f"Fetch {remote} failed")
                return
        finally:
            QApplication.restoreOverrideCursor()
            if isinstance(button, QToolButton):
                button.setEnabled(True)
        self.refresh()
        # refresh() 重建 tabs 後預設切回 local，這裡切回原本正在看的 remote tab
        if remote in self.branch_tab_order:
            self.branch_tab_bar.setCurrentIndex(self.branch_tab_order.index(remote))

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        recent = load_recent_paths()
        if not recent:
            empty_action = QAction("(No recent paths)", self)
            empty_action.setEnabled(False)
            self.recent_menu.addAction(empty_action)
            return
        for p in recent:
            row = RecentPathRow(p, self.recent_menu)
            row.open_requested.connect(self._open_recent_path)
            row.remove_requested.connect(self._remove_recent_path)
            action = QWidgetAction(self.recent_menu)
            action.setDefaultWidget(row)
            self.recent_menu.addAction(action)

    def _open_recent_path(self, path: str):
        self.main_menu.close()
        self._open_path(path)

    def _remove_recent_path(self, path: str):
        recent = load_recent_paths()
        norm = normalize_path(path)
        if norm in recent:
            recent.remove(norm)
            save_recent_paths(recent)
        self._refresh_recent_menu()

    def _build_settings_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setStyleSheet(
            "QDialog { background-color: #2b2b2b; color: #ffffff; }"
            "QLabel { color: #ffffff; }"
        )
        layout = QFormLayout(dlg)
        layout.addRow("Font Size:", self.font_size_spin)
        self.settings_dialog = dlg

    def open_settings_dialog(self):
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def on_font_size_changed(self, value: int):
        self.view.font_size = value
        save_font_size(value)

        branch_font = self.branch_list.font()
        branch_font.setPointSize(value)
        self.branch_list.setFont(branch_font)

        self.detail_panel.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #dddddd; "
            f"font-family: Consolas; font-size: {value}pt; border: none; padding: 8px; }}"
        )

        # 不必重新讀 git log，直接拿上次的資料用新字體大小重畫即可
        if self.last_render_data:
            prev_focused = self.view.focused_hash
            prev_branch_hashes = self.view.branch_highlight_hashes
            commits, edges, hash_to_commit, max_lanes = self.last_render_data
            self.view.render_commits(commits, edges, hash_to_commit, max_lanes)
            # render_commits 內部的 clear() 會重置 focus/高亮狀態，重畫後還原回去
            if prev_focused:
                self.view.focused_hash = prev_focused
                self.view.apply_focus_style()
            elif prev_branch_hashes is not None:
                self.view.branch_highlight_hashes = prev_branch_hashes
                self.view.apply_focus_style()

    def _relayout(self, mainline_branch: Optional[str]):
        """用 self.raw_commits（已讀好的原始 commit 清單）重新計算 lane/主線並重畫，
        不必重讀 git log。重畫後會呼叫 render_commits()，任何 focus/高亮狀態需由
        呼叫端在這之後自行還原。"""
        if self.raw_commits is None:
            return None
        tip_hash = branch_tip_hash(self.repo_path, mainline_branch) if mainline_branch else None
        commits, edges, hash_to_commit = compute_layout(self.raw_commits, mainline_tip_hash=tip_hash)
        max_lanes = max((c.lane for c in commits), default=0)
        self.view.render_commits(commits, edges, hash_to_commit, max_lanes)
        self.last_render_data = (commits, edges, hash_to_commit, max_lanes)
        self.mainline_branch = mainline_branch
        return tip_hash

    def clear_branch_selection(self):
        if self.selected_branch_name is None:
            return
        self.selected_branch_name = None
        self.branch_list.clearSelection()
        self._relayout(self.default_branch_name)
        self.view.clear_branch_highlight()
        self.status.showMessage("已取消分支高亮，主線恢復為預設分支")

    def _rebuild_branch_tabs(self, tab_data: dict):
        """依 tab_data 重建 tab bar（第一個永遠是 local，其餘照 remote 出現順序），
        並自動切到第一個 tab、填入對應的分支清單。每個 remote tab 右側會內嵌一個
        小 fetch 按鈕，只 fetch 那個 remote 自己，不是全域 fetch --all。"""
        self.branch_tab_data = tab_data
        order = ["local"] + [k for k in tab_data.keys() if k != "local"]
        self.branch_tab_order = order

        self._remote_fetch_buttons = {}  # tab key -> 內嵌在該 tab 上的 fetch 按鈕，只在該 tab 被選到時顯示
        self.branch_tab_bar.blockSignals(True)
        while self.branch_tab_bar.count() > 0:
            self.branch_tab_bar.removeTab(0)
        for idx, key in enumerate(order):
            self.branch_tab_bar.addTab(key)
            if key != "local":
                fetch_btn = QToolButton()
                fetch_btn.setText("⭳")
                fetch_btn.setCursor(Qt.PointingHandCursor)
                fetch_btn.setFixedSize(18, 18)
                fetch_btn.setToolTip(f"Fetch {key} (git fetch {key} --prune)")
                fetch_btn.setStyleSheet(
                    "QToolButton { background-color: transparent; color: #aaaaaa; "
                    "font-size: 10pt; border: none; padding: 0px; }"
                    "QToolButton:hover { color: #ffffff; }"
                )
                fetch_btn.clicked.connect(lambda checked=False, remote=key: self.fetch_remote(remote))
                fetch_btn.setVisible(False)
                self.branch_tab_bar.setTabButton(idx, QTabBar.RightSide, fetch_btn)
                self._remote_fetch_buttons[key] = fetch_btn
        self.branch_tab_bar.blockSignals(False)

        self.branch_tab_bar.setCurrentIndex(0)
        self.show_all_checkbox.setVisible(True)
        self._populate_branch_list("local")
        self._update_fetch_button_visibility("local")

    def _populate_branch_list(self, tab_key: str):
        self.branch_list.clear()
        self.selected_branch_name = None
        show_all = self.show_all_checkbox.isChecked()
        for display_name, full_ref in self.branch_tab_data.get(tab_key, []):
            is_main = display_name == self.default_branch_name
            is_merged = full_ref in self.merged_ref_names
            if not show_all and is_merged and not is_main:
                continue  # 預設只顯示還沒合併到主分支的 branch；主分支永遠顯示
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, full_ref)
            if show_all and is_merged and not is_main:
                item.setForeground(QBrush(QColor("#888888")))  # 已合併，亮度降低；主分支不降低
            self.branch_list.addItem(item)

    def _on_show_all_toggled(self, _state):
        index = self.branch_tab_bar.currentIndex()
        if 0 <= index < len(self.branch_tab_order):
            self._populate_branch_list(self.branch_tab_order[index])

    def _update_fetch_button_visibility(self, active_key: str):
        """只有目前被選到的 remote tab 顯示它自己的 fetch 按鈕。"""
        for key, btn in self._remote_fetch_buttons.items():
            btn.setVisible(key == active_key)

    def _on_branch_tab_changed(self, index: int):
        if not (0 <= index < len(self.branch_tab_order)):
            return
        tab_key = self.branch_tab_order[index]
        self._populate_branch_list(tab_key)
        self._update_fetch_button_visibility(tab_key)
        self._relayout(self.default_branch_name)
        self.view.clear_branch_highlight()

    def on_branch_clicked(self, item: QListWidgetItem):
        name = item.data(Qt.UserRole) or item.text()
        if self.selected_branch_name == name:
            # 再點一次同一個分支 -> 取消高亮，主線恢復為預設分支
            self.selected_branch_name = None
            self.branch_list.clearSelection()
            self._relayout(self.default_branch_name)
            self.view.clear_branch_highlight()
            self.status.showMessage("已取消分支高亮，主線恢復為預設分支")
            return
        self.selected_branch_name = name
        tip_hash = self._relayout(name)
        hashes = branch_ancestor_hashes(self.repo_path, name)
        self.view.set_branch_highlight(hashes)
        if tip_hash:
            self.view.scroll_to_commit(tip_hash)
        self.status.showMessage(f"已將 '{name}' 設為主線，並標示其 {len(hashes)} 個 commits")

    def _clear_repo_state(self):
        """清掉目前畫面上跟舊 repo 有關的所有資料（graph/branch tabs/選取狀態)，
        避免切到一個空的或載入失敗的 repo 時，畫面還留著上一個 repo 的殘影。"""
        self.raw_commits = None
        self.last_render_data = None
        self.view.clear()
        self.branch_tab_data = {}
        self.branch_tab_order = []
        self.branch_tab_bar.blockSignals(True)
        while self.branch_tab_bar.count() > 0:
            self.branch_tab_bar.removeTab(0)
        self.branch_tab_bar.blockSignals(False)
        self.branch_list.clear()
        self.selected_branch_name = None
        self.default_branch_name = None
        self.mainline_branch = None
        self.merged_ref_names = set()
        self.show_all_checkbox.setVisible(False)

    def refresh(self, path: Optional[str] = None, _retry_after_fix: bool = False):
        if path is None:
            path = self.repo_path
        path = (path or "").strip()
        if not path:
            return
        self.repo_path = path
        self.path_display.setText(path)
        self._clear_repo_state()
        self.status.showMessage("Loading...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            commits = load_commits(path, branch_scope="--all", limit=2000)
            if not commits:
                self.status.showMessage("找不到任何 commit")
                return
            self.raw_commits = commits
            branch_names = local_branch_names(path)
            self.default_branch_name = get_default_branch_name(path, branch_names) or (
                branch_names[0] if branch_names else None
            )
            self.mainline_branch = self.default_branch_name
            self.merged_ref_names = (
                merged_ref_names(path, self.default_branch_name) if self.default_branch_name else set()
            )
            tip_hash = branch_tip_hash(path, self.mainline_branch) if self.mainline_branch else None
            commits, edges, hash_to_commit = compute_layout(commits, mainline_tip_hash=tip_hash)
            max_lanes = max((c.lane for c in commits), default=0)
            self.view.render_commits(commits, edges, hash_to_commit, max_lanes)
            self.last_render_data = (commits, edges, hash_to_commit, max_lanes)

            tab_data = {"local": [(n, n) for n in branch_names]}
            for remote in list_remote_names(path):
                remote_names = remote_branch_names(path, remote)
                if self.default_branch_name and self.default_branch_name in remote_names:
                    remote_names.remove(self.default_branch_name)
                    remote_names.insert(0, self.default_branch_name)
                tab_data[remote] = [(n, f"{remote}/{n}") for n in remote_names]
            self._rebuild_branch_tabs(tab_data)

            self.status.showMessage(f"已載入 {len(commits)} 個 commits — {path}")
            self._remember_path(path)
        except Exception as e:
            error_text = str(e)
            if not _retry_after_fix and "dubious ownership" in error_text:
                if self._try_fix_safe_directory(error_text):
                    self.refresh(_retry_after_fix=True)
                    return
            tb = traceback.format_exc()
            show_error_dialog(self, "錯誤", f"{e}\n\n--- 詳細錯誤 (debug用) ---\n{tb}")
            self.status.showMessage("載入失敗")
        finally:
            QApplication.restoreOverrideCursor()

    def _try_fix_safe_directory(self, error_text: str) -> bool:
        """偵測到 git 的 'dubious ownership' 錯誤時，從錯誤訊息中擷取 git 建議的
        safe.directory 設定值，詢問使用者是否要自動執行 git config 修復。"""
        match = re.search(r"git config --global --add safe\.directory '(.+?)'", error_text)
        if not match:
            return False
        safe_value = match.group(1)
        agreed = show_question_dialog(
            self, "需要設定 Git 安全目錄",
            f"這個資料夾被 Git 視為不受信任的擁有權（dubious ownership），"
            f"通常發生在路徑來自 WSL 或網路磁碟機時。\n\n"
            f"是否要自動執行以下指令來信任這個路徑？\n\n"
            f"git config --global --add safe.directory \"{safe_value}\"\n\n"
            f"（這只會把這個路徑加入你個人的 git 信任清單，不會更動 repo 本身的任何內容）"
        )
        if not agreed:
            return False
        result = run_git(
            ["git", "config", "--global", "--add", "safe.directory", safe_value]
        )
        if result.returncode != 0:
            show_error_dialog(self, "設定失敗", result.stderr.strip() or "git config 執行失敗")
            return False
        self.status.showMessage("已設定 safe.directory，重新載入中...")
        return True

    def _remember_path(self, path: str):
        norm_path = normalize_path(path)
        recent = load_recent_paths()  # 內部已正規化
        if norm_path in recent:
            recent.remove(norm_path)
        recent.insert(0, norm_path)
        recent = recent[:MAX_RECENT_PATHS]
        save_recent_paths(recent)
        self._refresh_recent_menu()
        self.path_display.setText(norm_path)  # 顯示統一後的寫法，跟歷史清單一致


def main():
    app = QApplication(sys.argv)
    # 強制錯誤視窗/狀態列維持固定配色，避免系統深色主題造成黑底黑字看不到
    app.setStyleSheet("""
        QMessageBox { background-color: #f0f0f0; }
        QMessageBox QLabel { color: #000000; }
        QMessageBox QPushButton { color: #000000; background-color: #e0e0e0; padding: 4px 12px; }
        QStatusBar { color: #dddddd; background-color: #2b2b2b; }
        QToolBar { background-color: #3a3a3a; spacing: 6px; }
        QToolBar QToolButton { color: #ffffff; padding: 4px 8px; }
        QLabel { color: #dddddd; }
        QLineEdit { background-color: #1e1e1e; color: #ffffff; border: 1px solid #555; padding: 2px 4px; }
    """)
    repo_path = sys.argv[1] if len(sys.argv) > 1 else None
    win = MainWindow(repo_path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
