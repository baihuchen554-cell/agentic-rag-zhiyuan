"""用户名账号、个人资料、可撤销会话与验证请求绑定。"""

from contextlib import contextmanager
import hashlib
import hmac
import io
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

COOKIE = "knowva_session"
VISITOR_COOKIE = "knowva_visitor"


class AccountError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${value}"


def password_matches(password, stored):
    _, salt, _ = stored.split("$")
    return hmac.compare_digest(password_hash(password, salt), stored)


def validate_password(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise AccountError("密码需要 10–128 个字符。")
    if password.isspace() or password.isdigit() or password.isalpha():
        raise AccountError("请组合使用字母、数字或符号，避免仅使用一种字符。")


class AccountStore:
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL, password TEXT NOT NULL,
                    recovery TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS challenges (
                    id TEXT PRIMARY KEY, visitor TEXT NOT NULL, answer TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS limits (
                    key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS queue_owners (
                    hash TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS event_owners (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS uploads (
                    path TEXT NOT NULL, owner TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(path, owner));
            """)
            # 原账号数据库就地增加头像字段，保留用户 ID、会话和个人知识库。
            columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
            if "avatar" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN avatar BLOB")
            if "disabled" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
            if "role" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member'")
            db.execute('''CREATE TABLE IF NOT EXISTS admin_audit (
                id INTEGER PRIMARY KEY, actor TEXT NOT NULL, target TEXT NOT NULL,
                action TEXT NOT NULL, created REAL NOT NULL)''')
        self.path.chmod(0o600)
        self.dummy_hash = password_hash("not-a-real-password")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def limit(self, key, maximum, seconds):
        now = self.clock()
        with self.connect() as db:
            db.execute("DELETE FROM limits WHERE expires < ?", (now,))
            db.execute("INSERT INTO limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1",
                       (key, now + seconds))
            count = db.execute("SELECT count FROM limits WHERE key=?", (key,)).fetchone()[0]
        if count > maximum:
            raise AccountError("操作过于频繁，请稍后再试。", 429)

    def challenge(self, visitor, action):
        token = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute("DELETE FROM challenges WHERE expires < ? OR visitor=?", (self.clock(), digest(visitor)))
            db.execute("INSERT INTO challenges VALUES (?,?,?,?)",
                       (token, digest(visitor), action, self.clock() + 300))
        return token

    def consume_challenge(self, token, visitor, action):
        with self.connect() as db:
            row = db.execute("DELETE FROM challenges WHERE id=? RETURNING *", (token,)).fetchone()
        valid = (row is not None and row["expires"] > self.clock()
                 and hmac.compare_digest(row["visitor"], digest(visitor))
                 and row["answer"] == action)
        if not valid:
            raise AccountError("人机验证已过期或不属于当前操作，请重新验证。")

    def register(self, username, display_name, password):
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,23}", username):
            raise AccountError("用户名需以字母开头，包含 3–24 位字母、数字或下划线。")
        if not 1 <= len(display_name.strip()) <= 24:
            raise AccountError("昵称需要 1–24 个字符。")
        validate_password(password)
        user_id, recovery = uuid.uuid4().hex, secrets.token_urlsafe(24)
        hashed = password_hash(password)
        try:
            with self.connect() as db:
                db.execute("INSERT INTO users (id,username,display_name,password,recovery,created) VALUES (?,?,?,?,?,?)",
                           (user_id, username, display_name.strip(), hashed, digest(recovery), self.clock()))
        except sqlite3.IntegrityError:
            raise AccountError("这个用户名已被使用，请换一个。", 409) from None
        return self.public_user(dict(id=user_id, username=username, display_name=display_name.strip(), avatar=None)), recovery

    @staticmethod
    def public_user(row):
        row = dict(row)
        avatar = row["avatar"]
        return {**{key: row[key] for key in ("id", "username", "display_name")},
                "avatar_url": f"/account/avatar/{row['id']}?v={hashlib.sha256(avatar).hexdigest()[:16]}" if avatar else None,
                "role":row.get('role','member')}

    def login(self, username, password):
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
        valid = password_matches(password, row["password"] if row else self.dummy_hash)
        if row is None or not valid or row['disabled']:
            raise AccountError("用户名或密码不正确。", 401)
        return self.public_user(row)

    def new_session(self, user_id, remember=False):
        token = secrets.token_urlsafe(32)
        seconds = (30 if remember else 1) * 86400
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires < ?", (self.clock(),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (digest(token), user_id, self.clock() + seconds))
        return token, seconds

    def user(self, token):
        if not token:
            return None
        with self.connect() as db:
            row = db.execute("""SELECT users.id, username, display_name, avatar, role FROM users JOIN sessions
                ON users.id=sessions.user_id WHERE sessions.token=? AND expires>? AND users.disabled=0""", (digest(token), self.clock())).fetchone()
        return self.public_user(row) if row else None

    def update_profile(self, user_id, display_name):
        name = display_name.strip()
        if not 1 <= len(name) <= 24 or any(ord(c) < 32 for c in name):
            raise AccountError("姓名需要 1–24 个可显示字符。")
        with self.connect() as db:
            db.execute("UPDATE users SET display_name=? WHERE id=?", (name, user_id))

    def avatar(self, user_id):
        with self.connect() as db:
            row = db.execute("SELECT avatar FROM users WHERE id=?", (user_id,)).fetchone()
        return row[0] if row else None

    def set_avatar(self, user_id, content):
        if content is not None:
            if not content or len(content) > 2 * 1024 * 1024:
                raise AccountError("请选择不超过 2 MB 的图片。", 413)
            try:
                with Image.open(io.BytesIO(content)) as original:
                    if original.format not in {"JPEG", "PNG", "WEBP"}:
                        raise AccountError("头像仅支持 JPG、PNG 或 WebP 图片。")
                    if original.width * original.height > 8_000_000:
                        raise AccountError("图片尺寸过大，请使用不超过 800 万像素的图片。")
                    image = ImageOps.fit(ImageOps.exif_transpose(original).convert("RGB"),
                                         (256, 256), method=Image.Resampling.LANCZOS)
                    output = io.BytesIO()
                    image.save(output, format="WEBP", quality=85)
                    content = output.getvalue()
            except AccountError:
                raise
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                raise AccountError("无法读取这张图片，请换一张 JPG、PNG 或 WebP 图片。") from None
        with self.connect() as db:
            db.execute("UPDATE users SET avatar=? WHERE id=?", (content, user_id))

    def change_password(self, user_id, current_password, new_password):
        validate_password(new_password)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT password FROM users WHERE id=?", (user_id,)).fetchone()
            if not row or not password_matches(current_password, row[0]):
                raise AccountError("当前密码不正确。", 401)
            if current_password == new_password:
                raise AccountError("新密码不能与当前密码相同。")
            db.execute("UPDATE users SET password=? WHERE id=?", (password_hash(new_password), user_id))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (digest(token),))

    def recover(self, username, recovery, password):
        validate_password(password)
        next_recovery = secrets.token_urlsafe(24)
        with self.connect() as db:
            row = db.execute("SELECT id,recovery,disabled FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
            if row is None or row['disabled'] or not hmac.compare_digest(row["recovery"], digest(recovery.strip())):
                raise AccountError("用户名或恢复码不正确。", 401)
            db.execute("UPDATE users SET password=?,recovery=? WHERE id=?",
                       (password_hash(password), digest(next_recovery), row["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        return next_recovery

    def bind_queue(self, session_hash, owner):
        if not isinstance(session_hash, str) or not session_hash or len(session_hash) > 128:
            raise AccountError("页面会话无效，请刷新页面。", 400)
        with self.connect() as db:
            db.execute("DELETE FROM queue_owners WHERE expires < ?", (self.clock(),))
            db.execute("INSERT OR IGNORE INTO queue_owners VALUES (?,?,?)", (session_hash, owner, self.clock() + 86400))
            actual = db.execute("SELECT owner FROM queue_owners WHERE hash=?", (session_hash,)).fetchone()[0]
        if actual != owner:
            raise AccountError("页面会话不属于当前账号，请刷新页面。", 403)

    def record_upload(self, path, owner):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO uploads VALUES (?,?,?)", (str(Path(path).resolve()), owner, self.clock()))

    def record_event(self, event_id, owner):
        with self.connect() as db:
            db.execute("DELETE FROM event_owners WHERE expires < ?", (self.clock(),))
            db.execute("INSERT OR REPLACE INTO event_owners VALUES (?,?,?)", (event_id, owner, self.clock() + 86400))

    def check_event(self, event_id, owner):
        if not isinstance(event_id, str):
            raise AccountError("任务标识无效。", 403)
        with self.connect() as db:
            row = db.execute("SELECT owner FROM event_owners WHERE id=? AND expires>?", (event_id, self.clock())).fetchone()
        if row is None or row["owner"] != owner:
            raise AccountError("任务不属于当前账号。", 403)

    def owns_upload(self, path, owner):
        import config
        with self.connect() as db:
            return bool(db.execute("SELECT 1 FROM uploads WHERE path=? AND owner=? AND created>?",
                                   (str(Path(path).resolve()), owner, self.clock()-config.UPLOAD_TTL_SECONDS)).fetchone())

    def expired_uploads(self, seconds):
        with self.connect() as db:
            return [row[0] for row in db.execute('SELECT path FROM uploads GROUP BY path HAVING MAX(created)<?',
                                                (self.clock()-seconds,))]

    def forget_upload(self, path):
        with self.connect() as db:
            db.execute('DELETE FROM uploads WHERE path=?',(str(path),))

    def list_users(self, limit=50, offset=0):
        with self.connect() as db:
            rows = db.execute('SELECT id,username,display_name,role,disabled,created FROM users ORDER BY created DESC,id LIMIT ? OFFSET ?',
                              (limit,offset)).fetchall()
            total = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        return {'users':[dict(row) for row in rows], 'total':total}

    def require_enabled(self, user_id):
        with self.connect() as db:
            exists = db.execute('SELECT 1 FROM users WHERE id=? AND disabled=0',(user_id,)).fetchone()
        if not exists:
            raise AccountError('账号已停用，请联系站点维护者。',403)

    def set_status(self, user_id, disabled, actor):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT role,disabled FROM users WHERE id=?',(user_id,)).fetchone()
            if not row:
                raise AccountError('账号不存在。',404)
            if disabled and row['role']=='admin' and not row['disabled']:
                count = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0").fetchone()[0]
                if count <= 1:
                    raise AccountError('不能停用最后一个可用的管理员。',409)
            db.execute('UPDATE users SET disabled=? WHERE id=?',(int(disabled),user_id))
            if disabled:
                db.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
            db.execute('INSERT INTO admin_audit(actor,target,action,created) VALUES (?,?,?,?)',
                       (actor,user_id,'disable' if disabled else 'enable',self.clock()))

    def grant_admin(self, username):
        with self.connect() as db:
            row = db.execute('SELECT id FROM users WHERE username=?',(username.strip().lower(),)).fetchone()
            if not row:
                raise AccountError('账号不存在，请先通过网站注册。',404)
            db.execute("UPDATE users SET role='admin' WHERE id=?",(row['id'],))
            db.execute('INSERT INTO admin_audit(actor,target,action,created) VALUES (?,?,?,?)',
                       ('server-console',row['id'],'grant-admin',self.clock()))
