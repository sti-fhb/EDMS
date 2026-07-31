"""排程 leader 選舉起手包（US11 FR-02）。

EDMS 預設**單一實例**部署，直接視為 leader；多實例部署需以此擴充（如 DB advisory lock /
選舉 token）確保同一時間只有一個實例觸發排程，避免重複執行。
"""


def is_leader() -> bool:
    """本實例是否為排程 leader（唯一觸發者）。

    MVP：單一實例恆為 leader。多實例部署時於此改為真正的選舉判定。
    """
    return True
