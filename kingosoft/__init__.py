"""kingosoft —— 高校掌上校园接口的最小可用封装。

四个模块，一条链路：

    envelope  请求外壳（协议，可替换）
    client    学校解析 / 登录 / 会话续期
    kb        学期 / 单周课表 / 今日课程 / 班级
    checkin   签到状态 / 提交 / 距离 / 落库核验

用法：

    from kingosoft import Client, Checkin
    from kingosoft import kb

    c = Client(xxdm="SCHOOL_CODE", login_id="STUDENT_NO", password="PASSWORD")
    c.login()

    terms = kb.terms(c)
    table = kb.week_table(c, terms[0]["id"])        # week=0 → 自动探测当前周
    courses = table.today()

    ck = Checkin(c, xnxq=terms[0]["id"])
    for course in courses:
        st = ck.state(course)
        if st.active and st.qdfs in ("1", "2"):     # 定位 / 手势
            ck.submit_location(course, st)
            print(ck.verify(course))

只用标准库 + requests。失败一律抛 `ApiError`，不静默。
"""
from .checkin import QDZT, STATE, Checkin, State, distance_m, jc_hit, jc_nums, nearby
from .client import ApiError, Client, School, VersionGateError, js_escape
from .envelope import PlainEnvelope, Envelope, DEVICE_MODEL
from .kb import Course, WeekTable, my_class, terms, week_table

__version__ = "0.1.0"

__all__ = [
    "QDZT",
    "STATE",
    "ApiError",
    "Checkin",
    "Client",
    "Course",
    "DEVICE_MODEL",
    "Envelope",
    "PlainEnvelope",
    "School",
    "State",
    "VersionGateError",
    "WeekTable",
    "distance_m",
    "jc_hit",
    "jc_nums",
    "js_escape",
    "my_class",
    "nearby",
    "terms",
    "week_table",
]
