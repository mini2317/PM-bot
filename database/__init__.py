from .base import BaseDB
from .pages import PageMixin
from .users import UserMixin
from .meetings import MeetingMixin
from .projects import ProjectMixin
from .repos import RepoMixin
from .settings import SettingsMixin

class DBManager(BaseDB, UserMixin, MeetingMixin, ProjectMixin, RepoMixin, SettingsMixin, PageMixin):
    """
    모든 DB 기능을 통합 관리하는 클래스.
    BaseDB 및 각 기능별 Mixin을 상속받습니다.
    """
    pass