import pygame
import sys
import random
import math
import socket
import json
import threading
from collections import deque

# ─── Window / Timing ──────────────────────────────────────────────────────────
WIDTH, HEIGHT = 960, 620
FPS        = 60
ROUND_TIME = 30

# ─── Physics Constants ────────────────────────────────────────────────────────
GRAVITY          = 0.65
MAX_FALL         = 20.0
BASE_SPEED       = 5.2
ACCEL            = 2.2
AIR_ACCEL        = 1.2
FRICTION         = 0.78
AIR_FRICTION     = 0.96
JUMP_POWER       = -14.0
WALLJUMP_X       = 7.5
WALLJUMP_Y       = -13.0
WALL_SLIDE_VEL   = 2.2
BHOP_WINDOW      = 6
BHOP_BOOST       = 1.08
MAX_BHOP_MULT    = 1.65
BHOP_DECAY_DELAY = 12
BHOP_DECAY_RATE  = 0.88

SLAM_VEL         = 22.0
SLAM_SHOCKWAVE_R = 110
SLAM_KNOCKBACK   = 14.0
SLAM_UPKICK      = -9.0

PLAYER_W, PLAYER_H = 28, 32
PLAT_H = 14
WALL_W = 14
GROUND_Y    = HEIGHT - 50
GROUND_RECT = pygame.Rect(0, GROUND_Y, WIDTH, HEIGHT - GROUND_Y)

PLAYER_DEFS = [
    ("P1", (50, 190, 255),  {"left": pygame.K_a,    "right": pygame.K_d,     "up": pygame.K_w,  "down": pygame.K_s, "ability": pygame.K_q}),
    ("P2", (255,  70,  70), {"left": pygame.K_LEFT, "right": pygame.K_RIGHT, "up": pygame.K_UP, "down": pygame.K_DOWN, "ability": pygame.K_PERIOD}),
    ("P3", (80,  230,  80), {"left": pygame.K_j,    "right": pygame.K_l,     "up": pygame.K_i,  "down": pygame.K_k, "ability": pygame.K_u}),
    ("P4", (255, 165,   0), {"left": pygame.K_F1,   "right": pygame.K_F3,    "up": pygame.K_F2, "down": pygame.K_F4, "ability": pygame.K_F5}),
]

# ─── Colors ───────────────────────────────────────────────────────────────────
BG_TOP, BG_BOT = (8, 6, 22), (18, 8, 36)
CROWN_COL, PLAT_COL, PLAT_TOP = (255, 215, 0), (52, 47, 82), (88, 78, 128)
WALL_COL, WALL_EDGE, GND_COL, GND_LINE = (68, 58, 100), (108, 93, 148), (38, 34, 62), (78, 68, 112)
TEXT_COL, DIM_COL = (225, 220, 255), (80, 74, 120)

# Global font cache
BHOP_FONT = None
DEBUG_MODE = False

ABILITIES = [
    {"id": "rocket",     "name": "Rocket",  "color": (255, 140,  40), "icon": "R", "desc": "Launch in facing direction", "cd": 180},
    {"id": "blink",      "name": "Blink",   "color": (160,  80, 255), "icon": "B", "desc": "Teleport dash forward",       "cd": 150},
    {"id": "bomb",       "name": "Bomb",    "color": (255,  60,  60), "icon": "X", "desc": "Throw a bouncing bomb",       "cd": 240},
    {"id": "grapple",    "name": "Grapple", "color": (80,  220, 180), "icon": "G", "desc": "Hook nearest surface",        "cd": 200},
    {"id": "shield",     "name": "Shield",  "color": (100, 180, 255), "icon": "S", "desc": "3s immunity + push players", "cd": 300},
    {"id": "slam_boost", "name": "Stomp+",  "color": (255, 200,  50), "icon": "*", "desc": "Slam shockwave 2x (passive)", "cd": 0},
]

PU_JUMP, PU_SPEED, PU_FREEZE, PU_GHOST = "jump", "speed", "freeze", "ghost"
PU_HEAVY, PU_GRAV = "heavy", "grav"
PU_COLORS = {
    PU_JUMP:(80,255,160),  PU_SPEED:(255,195,40),
    PU_FREEZE:(80,200,255), PU_GHOST:(190,80,255),
    PU_HEAVY:(180,100,40), PU_GRAV:(255,80,200),
}
PU_LABELS = {
    PU_JUMP:"JMP",  PU_SPEED:"SPD",
    PU_FREEZE:"FRZ", PU_GHOST:"GHO",
    PU_HEAVY:"HVY", PU_GRAV:"GRV",
}

# ─── Network Handler ──────────────────────────────────────────────────────────
class NetworkClient:
    def __init__(self, server_ip="127.0.0.1", port=5555):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_ip = server_ip
        self.port = port
        self.my_id = None
        self.level_layout = None
        self.latest_server_state = None
        self.connected = False

    def connect(self):
        try:
            self.socket.connect((self.server_ip, self.port))
            init_data = json.loads(self.socket.recv(1024 * 16).decode().split('\n')[0])
            self.my_id = init_data["player_id"]
            self.level_layout = init_data["level"]
            self.connected = True
            threading.Thread(target=self._receive_loop, daemon=True).start()
            return True
        except Exception as e:
            print(f"Network Connection Failed: {e}")
            return False

    def _receive_loop(self):
        buffer = ""
        while True:
            try:
                data = self.socket.recv(4096 * 8).decode()
                if not data: break
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self.latest_server_state = json.loads(line)
            except:
                break

    def send(self, payload):
        if not self.connected: return
        try:
            self.socket.sendall((json.dumps(payload) + "\n").encode())
        except:
            pass

# ─── Cosmetic Helpers ─────────────────────────────────────────────────────────
def lerp_color(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def make_bg(w, h):
    s = pygame.Surface((w, h))
    for y in range(h):
        pygame.draw.line(s, lerp_color(BG_TOP, BG_BOT, y / h), (0, y), (w, y))
    return s

class Particle:
    __slots__ = ("x","y","vx","vy","col","life","maxl","size")
    def __init__(self, x, y, vx, vy, col, life, size=3):
        self.x,self.y,self.vx,self.vy,self.col,self.life,self.maxl,self.size = x,y,vx,vy,col,life,life,size
    def update(self):
        self.x+=self.vx; self.y+=self.vy; self.vy+=0.18; self.vx*=0.97; self.life-=1
    def draw(self, surface):
        a = max(0, int(255 * self.life / self.maxl))
        r = max(1, int(self.size * self.life / self.maxl))
        s = pygame.Surface((r*2+1, r*2+1), pygame.SRCALPHA)
        pygame.draw.circle(s, (*self.col, a), (r, r), r)
        surface.blit(s, (int(self.x)-r, int(self.y)-r))

class ClientBomb:
    def __init__(self, x, y, fuse):
        self.x, self.y, self.fuse, self.r = x, y, fuse, 8
    def draw(self, surface, tick):
        urgency = 1.0 - self.fuse / 180
        col = lerp_color((60, 55, 90), (255, 60, 30), urgency)
        pygame.draw.circle(surface, col, (int(self.x), int(self.y)), self.r)
        pygame.draw.circle(surface, (255, 220, 80), (int(self.x), int(self.y)), self.r, 2)

class ClientGrapple:
    def __init__(self, x, y, attached, ax, ay):
        self.x, self.y, self.attached, self.ax, self.ay = x, y, attached, ax, ay
    def draw(self, surface, ox, oy):
        ex = self.ax if self.attached else self.x
        ey = self.ay if self.attached else self.y
        pygame.draw.line(surface, (180, 220, 200), (int(ox), int(oy)), (int(ex), int(ey)), 2)
        pygame.draw.circle(surface, (80, 220, 180), (int(ex), int(ey)), 5)

# ─── Tag Feed ─────────────────────────────────────────────────────────────────
tag_feed = []

def push_tag_feed(tagger_name, victim_name):
    if len(tag_feed) >= 4:
        tag_feed.pop(0)
    tag_feed.append({"text": f"{tagger_name} tagged {victim_name}!", "life": 200})

def update_draw_tag_feed(surface, font):
    dead = []
    for i, entry in enumerate(tag_feed):
        entry["life"] -= 1
        if entry["life"] <= 0:
            dead.append(entry); continue
        alpha_t = min(1.0, entry["life"] / 60)
        col = lerp_color(DIM_COL, (255, 215, 0), alpha_t)
        txt = font.render(entry["text"], True, col)
        surface.blit(txt, (WIDTH - txt.get_width() - 10, 10 + i * 22))
    for d in dead:
        if d in tag_feed: tag_feed.remove(d)

# ─── Player ───────────────────────────────────────────────────────────────────
class Player:
    def __init__(self, x, y, color, controls, name):
        self.name, self.color, self.controls = name, color, controls
        self.x, self.y, self.vx, self.vy = float(x), float(y), 0.0, 0.0
        self.w, self.h = PLAYER_W, PLAYER_H
        self.on_ground, self.on_wall, self.wall_normal = False, 0, 0
        self.jumps_left = 2
        self.land_timer, self.ground_timer = 0, 0
        self.bhop_mult, self.wall_jump_lock = 1.0, 0
        self.speed_boost, self.frozen, self.ghost, self.jump_boost = 0, 0, 0, 0
        self.slamming, self.slam_cd, self.slam_hit = False, 0, False
        self.ability_id, self.ability_cd = "none", 0
        self.shield_up, self.facing = 0, 1
        self.squish, self.stretch = 0, 0
        self.trail, self.particles, self.sparks = [], [], []
        self.bombs = []
        self.grapple_obj = None
        self.outbound_events = []

        # NEW: post-tag invulnerability
        self.invul_frames = 0

        # NEW: slide mechanic
        self.sliding = False
        self.slide_cd = 0

        # NEW: extra power-up states
        self.heavy = 0       # frames of heavy power-up remaining
        self.grav_flip = 0   # frames of gravity-flip remaining

        # NEW: ghost trail positions
        self.pos_trail = deque(maxlen=4)

        # NEW: combo tracking
        self.last_tagged_id = None
        self.combo_count = 0

        # NEW: ability use stats for end screen
        self.ability_uses = {}

    @property
    def rect(self):
        # Slide reduces hitbox height
        h = self.h // 2 if self.sliding else self.h
        return pygame.Rect(int(self.x), int(self.y) + (self.h - h), self.w, h)

    @property
    def center(self):
        return (self.x + self.w / 2, self.y + self.h / 2)

    def effective_gravity(self):
        if self.grav_flip > 0: return -GRAVITY
        if self.heavy > 0: return GRAVITY * 2.0
        return GRAVITY

    def run_speed(self):
        s = BASE_SPEED * self.bhop_mult
        if self.speed_boost > 0: s *= 1.45
        if self.heavy > 0: s *= 0.65
        return s

    def use_ability(self, solids):
        if self.ability_id in ("none", "slam_boost") or self.ability_cd > 0 or self.frozen > 0:
            return
        adef = next((a for a in ABILITIES if a["id"] == self.ability_id), None)
        if not adef: return

        self.ability_uses[self.ability_id] = self.ability_uses.get(self.ability_id, 0) + 1

        if self.ability_id == "rocket":
            self.vx = self.facing * 16.0; self.vy = -5.0
            self.ability_cd = adef["cd"]
        elif self.ability_id == "blink":
            nx = max(0, min(WIDTH - self.w, self.x + self.facing * 160))
            if not any(pygame.Rect(int(nx), int(self.y), self.w, self.h).colliderect(s) for s in solids):
                self.x = nx
            self.ability_cd = adef["cd"]
        elif self.ability_id == "bomb":
            self.bombs.append({"x": self.x+self.w/2, "y": self.y,
                                "vx": self.facing*7.0+self.vx*0.3, "vy": -5.0, "fuse": 180})
            self.ability_cd = adef["cd"]
        elif self.ability_id == "grapple":
            if not self.grapple_obj:
                self.grapple_obj = {"x": self.x+self.w/2, "y": self.y+self.h/2,
                                    "vx": self.facing*18.0, "vy": -4.0,
                                    "attached": False, "ax": 0, "ay": 0, "life": 40}
                self.ability_cd = adef["cd"]
        elif self.ability_id == "shield":
            self.shield_up = 180
            self.ability_cd = adef["cd"]
            self.outbound_events.append({"type": "shield_push",
                                         "cx": self.center[0], "cy": self.center[1]})

    def try_slide(self, keys):
        if self.sliding or self.slide_cd > 0 or not self.on_ground or self.frozen:
            return
        if keys[self.controls["down"]] and abs(self.vx) > 3.0:
            self.sliding = True
            self.slide_cd = 45

    def update(self, keys, solids):
        self.pos_trail.append((self.x, self.y))
        grav = self.effective_gravity()

        # Slide update
        if self.sliding:
            self.vx *= 0.95
            if abs(self.vx) < 1.2 or not self.on_ground:
                self.sliding = False
        else:
            self.try_slide(keys)

        if self.frozen == 0 and not self.sliding:
            left  = keys[self.controls["left"]]
            right = keys[self.controls["right"]]
            wish  = (1 if right else 0) - (1 if left else 0)
            if wish != 0: self.facing = wish
            if not self.slamming:
                target = self.run_speed() * wish
                accel = ACCEL if self.on_ground else AIR_ACCEL
                if wish > 0:   self.vx = min(self.vx + accel, target) if self.vx < target else self.vx
                elif wish < 0: self.vx = max(self.vx - accel, target) if self.vx > target else self.vx
                else:          self.vx *= (FRICTION if self.on_ground else AIR_FRICTION)
        elif not self.sliding:
            self.vx *= 0.72

        # Wall slide (only when gravity normal)
        if self.on_wall != 0 and not self.on_ground and self.vy > WALL_SLIDE_VEL \
                and not self.slamming and self.grav_flip == 0:
            self.vy = WALL_SLIDE_VEL

        # Grapple pull
        if self.grapple_obj and self.grapple_obj.get("attached"):
            dx = self.grapple_obj["ax"] - self.center[0]
            dy = self.grapple_obj["ay"] - self.center[1]
            d = math.sqrt(dx**2 + dy**2) + 0.01
            if d > 20:
                pull = min(0.9, 80 / d)
                self.vx += dx / d * pull * 2.2
                self.vy += dy / d * pull * 2.2
            else:
                self.grapple_obj = None

        # Apply gravity (clamped direction-aware)
        if grav > 0:
            self.vy = min(self.vy + grav, MAX_FALL)
        else:
            self.vy = max(self.vy + grav, -MAX_FALL)

        # X movement + wall collision
        self.x += self.vx
        if self.x < 0: self.x = 0; self.vx = 0
        if self.x + self.w > WIDTH: self.x = WIDTH - self.w; self.vx = 0

        self.on_wall = 0
        px = self.rect
        for solid in solids:
            if not px.colliderect(solid): continue
            if self.vx > 0:
                self.x = solid.left - self.w
                if self.wall_jump_lock == 0: self.on_wall = 1; self.wall_normal = -1
                self.vx = 0
            elif self.vx < 0:
                self.x = solid.right
                if self.wall_jump_lock == 0: self.on_wall = -1; self.wall_normal = 1
                self.vx = 0
            px = self.rect

        # Y movement + ground collision
        self.y += self.vy
        prev_ground = self.on_ground
        self.on_ground = False
        py = self.rect
        for solid in solids:
            if not py.colliderect(solid): continue
            if grav >= 0 and self.vy >= 0:
                # Normal gravity: land on top of solid
                if (int(self.y) - int(self.vy)) <= solid.top + 4:
                    self.y = solid.top - self.h
                    self.vy = 0; self.on_ground = True; self.on_wall = 0
                    if not prev_ground:
                        self.squish = 7; self.land_timer = BHOP_WINDOW; self.ground_timer = 0
                    if self.slamming and not self.slam_hit:
                        self.slam_hit = True; self.slamming = False
                        radius = SLAM_SHOCKWAVE_R * (2 if self.ability_id == "slam_boost" else 1)
                        if self.heavy > 0: radius = int(radius * 1.5)
                        self.outbound_events.append({"type": "shockwave",
                                                     "cx": self.center[0],
                                                     "cy": self.y + self.h, "r": radius})
                        self.slam_cd = 45
                    else:
                        self.slamming = False
                    self.jumps_left = 2
            elif grav < 0 and self.vy <= 0:
                # Flipped gravity: land on bottom of solid (ceiling walking)
                if (int(self.y) - int(self.vy)) >= solid.bottom - 4:
                    self.y = solid.bottom
                    self.vy = 0; self.on_ground = True; self.on_wall = 0
                    if not prev_ground:
                        self.squish = 7; self.land_timer = BHOP_WINDOW; self.ground_timer = 0
                    self.jumps_left = 2
            elif self.vy < 0 and grav >= 0:
                # Head bonk
                if (int(self.y) - int(self.vy)) >= solid.bottom - 4:
                    self.y = solid.bottom; self.vy = 0
            py = self.rect

        if self.on_ground:
            self.ground_timer += 1
            if self.ground_timer > BHOP_DECAY_DELAY:
                self.bhop_mult = max(1.0, self.bhop_mult * BHOP_DECAY_RATE)
        else:
            self.bhop_mult = max(1.0, self.bhop_mult * 0.998)

        # Grapple hook travel
        if self.grapple_obj:
            g = self.grapple_obj
            if not g["attached"]:
                g["life"] -= 1
                if g["life"] <= 0:
                    self.grapple_obj = None
                else:
                    g["vy"] += 0.3; g["x"] += g["vx"]; g["y"] += g["vy"]
                    gr = pygame.Rect(int(g["x"])-4, int(g["y"])-4, 8, 8)
                    for s in solids:
                        if gr.colliderect(s):
                            g["attached"] = True; g["ax"] = g["x"]; g["ay"] = g["y"]; break
                    if g["x"] < 0 or g["x"] > WIDTH or g["y"] < 0 or g["y"] > HEIGHT:
                        self.grapple_obj = None

        # Bomb simulation
        rem_bombs = []
        for b in self.bombs:
            b["fuse"] -= 1
            if b["fuse"] <= 0:
                self.outbound_events.append({"type": "bomb_explosion", "bx": b["x"], "by": b["y"]})
                continue
            b["vy"] = min(b["vy"] + 0.5, 18)
            b["x"] += b["vx"]; b["y"] += b["vy"]
            br = pygame.Rect(int(b["x"])-8, int(b["y"])-8, 16, 16)
            for s in solids:
                if br.colliderect(s):
                    if b["vy"] > 0 and b["y"] < s.centery: b["y"] = s.top - 8; b["vy"] = -b["vy"] * 0.6
                    elif b["vy"] < 0:                       b["y"] = s.bottom + 8; b["vy"] = -b["vy"] * 0.5
                    else:                                    b["vx"] = -b["vx"] * 0.7
            rem_bombs.append(b)
        self.bombs = rem_bombs

        # Tick all countdown attributes
        for attr in ("speed_boost","frozen","ghost","jump_boost","ability_cd","slam_cd",
                     "shield_up","squish","stretch","land_timer","wall_jump_lock",
                     "invul_frames","slide_cd","heavy","grav_flip"):
            v = getattr(self, attr)
            if v > 0: setattr(self, attr, v - 1)

    def jump(self):
        if self.frozen or self.slamming: return
        if self.on_wall != 0 and not self.on_ground:
            self.vx = self.wall_normal * WALLJUMP_X
            self.vy = WALLJUMP_Y * (-1 if self.grav_flip > 0 else 1)
            self.on_wall = 0; self.wall_jump_lock = 14; self.stretch = 10; return
        if self.land_timer > 0:
            self.bhop_mult = min(MAX_BHOP_MULT, self.bhop_mult * BHOP_BOOST)
            self.land_timer = 0
        if self.jumps_left > 0:
            power = JUMP_POWER * (1.20 if self.jump_boost > 0 else 1.0)
            self.vy = power * (-1 if self.grav_flip > 0 else 1)
            self.jumps_left -= 1; self.on_ground = False; self.stretch = 10

    def slam(self):
        if self.grav_flip > 0: return
        if self.on_ground or self.slam_cd > 0 or self.frozen or self.slamming: return
        self.slamming = True; self.vy = SLAM_VEL; self.vx *= 0.3; self.slam_hit = False

    def build_network_dict(self):
        return {
            "name": self.name, "x": self.x, "y": self.y, "vx": self.vx, "vy": self.vy,
            "facing": self.facing, "squish": self.squish, "stretch": self.stretch,
            "shield_up": self.shield_up, "ghost": self.ghost, "frozen": self.frozen,
            "slamming": self.slamming, "ability_id": self.ability_id, "ability_cd": self.ability_cd,
            "bhop_mult": self.bhop_mult,
            "bombs":   [{"x":b["x"],"y":b["y"],"fuse":b["fuse"]} for b in self.bombs],
            "grapple": self.grapple_obj,
            "invul_frames": self.invul_frames,
            "sliding": self.sliding,
            "heavy":    self.heavy,
            "grav_flip": self.grav_flip,
            "ability_uses": self.ability_uses,
            "trail": [[tx, ty] for tx, ty in self.pos_trail],
        }

# ─── Remote Player Renderer ───────────────────────────────────────────────────
def draw_network_player(surface, p_id, data, is_tagger, tick, tagger_age=0, debug=False):
    x, y = data["x"], data["y"]
    w, h = PLAYER_W, PLAYER_H
    col  = PLAYER_DEFS[int(p_id)][1]

    # Color tinting by state
    if data["shield_up"] > 0:          col = lerp_color(col, (100, 180, 255), 0.6)
    if data["ghost"] > 0:              col = lerp_color(col, (190, 80, 255),  0.5)
    if data["frozen"] > 0:             col = lerp_color(col, (120, 210, 255), 0.7)
    if data.get("heavy", 0) > 0:       col = lerp_color(col, (180, 100,  40), 0.5)
    if data.get("grav_flip", 0) > 0:   col = lerp_color(col, (255,  80, 200), 0.5)

    # Invulnerability flicker: skip every other 4-frame block
    if data.get("invul_frames", 0) > 0 and (tick // 4) % 2 == 0:
        return

    # Body dimensions
    dw, dh = w, h
    if data.get("sliding"):
        dh = h // 2
    elif data["squish"] > 0:
        dw = int(w * (1 + 0.26 * (data["squish"] / 7)))
        dh = int(h * (1 - 0.20 * (data["squish"] / 7)))
    elif data["stretch"] > 0:
        dw = int(w * (1 - 0.16 * (data["stretch"] / 10)))
        dh = int(h * (1 + 0.28 * (data["stretch"] / 10)))

    dx = int(x) + w // 2 - dw // 2
    dy = int(y) + h - dh

    # Ghost trail (high speed or sliding)
    if data.get("bhop_mult", 1.0) > 1.08 or data.get("sliding"):
        for ti, (tx, ty) in enumerate(data.get("trail", [])):
            trail_alpha = 20 * (ti + 1)
            ts = pygame.Surface((dw, dh), pygame.SRCALPHA)
            ts.fill((*col, trail_alpha))
            surface.blit(ts, (int(tx) + w//2 - dw//2, int(ty) + h - dh))

    # Tagger glow (rage-tinted after 15 s)
    if is_tagger:
        rage_t = min(1.0, max(0.0, (tagger_age - 900) / 900))
        glow_col = lerp_color(CROWN_COL, (255, 60, 30), rage_t)
        gr = dw // 2 + 13 + int(4 * math.sin(tick * 0.18))
        gsurf = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
        pygame.draw.circle(gsurf, (*glow_col, 48), (gr, gr), gr)
        surface.blit(gsurf, (dx + dw//2 - gr, dy + dh//2 - gr))

    # Body (flipped vertically when gravity-flipped)
    body = pygame.Surface((dw, dh), pygame.SRCALPHA)
    pygame.draw.rect(body, col, (0, 0, dw, dh), border_radius=8)
    if data.get("grav_flip", 0) > 0:
        body = pygame.transform.flip(body, False, True)
    surface.blit(body, (dx, dy))

    # Eyes
    ey     = dy + dh // 3
    facing = data["facing"]
    e1x = dx + dw * 2 // 5 if facing > 0 else dx + dw // 5
    e2x = dx + dw * 4 // 5 - 4 if facing > 0 else dx + dw * 3 // 5 - 4
    for ex in (e1x, e2x):
        pygame.draw.circle(surface, (255, 255, 255), (ex, ey), 4)
        pygame.draw.circle(surface, (12, 8, 22), (ex + facing, ey + 1), 2)

    # Crown
    if is_tagger:
        cx, cyt = dx + dw // 2, dy - 4
        pygame.draw.polygon(surface, CROWN_COL,
                            [(cx-10,cyt),(cx-5,cyt-9),(cx,cyt-4),(cx+5,cyt-9),(cx+10,cyt)])

    # Ability cooldown arc
    acd  = data.get("ability_cd", 0)
    adef = next((a for a in ABILITIES if a["id"] == data.get("ability_id","none")), None)
    if adef and adef["cd"] > 0 and acd > 0:
        fill = 1.0 - acd / adef["cd"]
        arc_rect = pygame.Rect(dx - 6, dy - 6, dw + 12, dh + 12)
        try:
            pygame.draw.arc(surface, adef["color"], arc_rect,
                            math.pi / 2, math.pi / 2 + fill * 2 * math.pi, 3)
        except Exception:
            pass

    # Name tag
    if BHOP_FONT:
        ns = BHOP_FONT.render(data.get("name",""), True, TEXT_COL)
        surface.blit(ns, (dx + dw//2 - ns.get_width()//2, dy - 20))

    # Bombs and grapple
    for b in data.get("bombs", []):
        ClientBomb(b["x"], b["y"], b["fuse"]).draw(surface, tick)
    if data.get("grapple"):
        g = data["grapple"]
        ClientGrapple(g["x"],g["y"],g["attached"],g["ax"],g["ay"]).draw(surface, x+w/2, y+h/2)

    # Bhop multiplier label
    if data.get("bhop_mult", 1.0) > 1.08 and BHOP_FONT:
        st = BHOP_FONT.render(f"x{data['bhop_mult']:.1f}", True, (255, 220, 60))
        surface.blit(st, (dx, dy - 22))

    # Debug hitboxes
    if debug:
        pygame.draw.rect(surface, (0, 255, 0),
                         pygame.Rect(int(x), int(y) + (h - dh), w, dh), 1)
        for b in data.get("bombs", []):
            pygame.draw.circle(surface, (255, 100, 0), (int(b["x"]), int(b["y"])), 90, 1)

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    pygame.init()
    global BHOP_FONT, DEBUG_MODE

    server_ip = input("Enter Server IP (Press Enter for Localhost): ").strip()
    if not server_ip: server_ip = "127.0.0.1"

    net = NetworkClient(server_ip=server_ip)
    if not net.connect():
        print("Could not connect to server.")
        return

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(f"TAG! Online — Player {net.my_id}")
    clock = pygame.time.Clock()

    bigfont   = pygame.font.SysFont("Consolas", 34, bold=True)
    font      = pygame.font.SysFont("Consolas", 24, bold=True)
    sm        = pygame.font.SysFont("Consolas", 14)
    BHOP_FONT = pygame.font.SysFont("Consolas", 11, bold=True)

    bg_surf = make_bg(WIDTH, HEIGHT)
    stars   = [(random.randint(0,WIDTH), random.randint(0,HEIGHT*2//3),
                random.randint(55,185)) for _ in range(100)]

    loaded_level = net.level_layout
    platforms = [pygame.Rect(*p) for p in loaded_level["platforms"]]
    walls     = [pygame.Rect(*w) for w in loaded_level["walls"]]
    solids    = [GROUND_RECT] + platforms + walls

    p_def        = PLAYER_DEFS[net.my_id]
    local_player = Player(400, 100, p_def[1], p_def[2], f"{p_def[0]} (You)")

    tick             = 0
    round_start_ticks = pygame.time.get_ticks()
    picker           = None
    last_game_state  = None

    # NEW state
    camera_shake = 0
    flash_alpha  = 0
    tagger_age   = 0   # frames current player has held the tag

    while True:
        tick += 1
        keys      = pygame.key.get_pressed()
        s_state   = net.latest_server_state

        current_game_state = s_state["game_state"] if s_state else "home"
        tagger_id  = str(s_state["tagger_idx"]) if s_state else "0"
        scores     = s_state["scores"] if s_state else [0,0,0,0]
        is_tagger  = (tagger_id == str(net.my_id))

        # Tagger rage counter
        tagger_age = tagger_age + 1 if is_tagger else 0

        # Desperation speed boost for tagger
        if is_tagger and current_game_state == "playing":
            rage_mult = min(1.25, 1.0 + (tagger_age / 60) * 0.02)
            local_player.bhop_mult = max(local_player.bhop_mult, rage_mult)

        # Reload map when server pushes a new level
        if s_state and s_state.get("level") != loaded_level:
            loaded_level = s_state["level"]
            platforms = [pygame.Rect(*p) for p in loaded_level["platforms"]]
            walls     = [pygame.Rect(*w) for w in loaded_level["walls"]]
            solids    = [GROUND_RECT] + platforms + walls

        # State transition housekeeping
        if current_game_state != last_game_state:
            if current_game_state in ("pick","playing"):
                round_start_ticks = pygame.time.get_ticks()
            if current_game_state == "pick":
                picker = None
            last_game_state = current_game_state

        # ── Events ────────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit(); sys.exit()

                if event.key == pygame.K_F12:
                    DEBUG_MODE = not DEBUG_MODE

                if current_game_state == "home" and event.key == pygame.K_SPACE:
                    net.send({"command": "start_game"})

                if current_game_state == "pick" and picker:
                    if event.key == local_player.controls["left"]:
                        picker["sel"] = (picker["sel"] - 1) % 3
                    if event.key == local_player.controls["right"]:
                        picker["sel"] = (picker["sel"] + 1) % 3
                    if event.key == local_player.controls["up"]:
                        local_player.ability_id = ABILITIES[picker["offers"][picker["sel"]]]["id"]
                        net.send({"command": "abilities_chosen"})

                if current_game_state == "playing":
                    if event.key == local_player.controls["up"]:
                        local_player.jump()
                    if event.key == local_player.controls["down"] and not local_player.sliding:
                        local_player.slam()
                    if event.key == local_player.controls["ability"]:
                        local_player.use_ability(solids)

                if current_game_state == "result" and event.key == pygame.K_SPACE:
                    net.send({"command": "next_round"})

        # ── Server event processing ────────────────────────────────────────
        if s_state and s_state.get("events"):
            for e in s_state["events"]:
                cx, cy = e.get("cx", 0), e.get("cy", 0)
                ddx = local_player.center[0] - cx
                ddy = local_player.center[1] - cy
                dist = math.sqrt(ddx**2 + ddy**2) + 0.01

                if e["type"] == "shockwave" and dist < e["r"]:
                    if local_player.frozen == 0 and local_player.shield_up == 0 \
                            and local_player.heavy == 0:
                        force = 1.0 - dist / e["r"]
                        local_player.vx += (ddx / dist) * SLAM_KNOCKBACK * force
                        local_player.vy += SLAM_UPKICK * force
                    camera_shake = max(camera_shake, int(max(0, 20 - dist / 50)))

                elif e["type"] == "bomb_explosion" and dist < 90:
                    force = 1.0 - dist / 90
                    local_player.vx += (ddx / dist) * 12 * force
                    local_player.vy = min(local_player.vy, -8 * force)
                    camera_shake = max(camera_shake, int(max(0, 20 - dist / 50)))

                elif e["type"] == "shield_push" and dist < 100:
                    local_player.vx += ddx / dist * 10
                    local_player.vy += ddy / dist * 10 - 4

                elif e["type"] == "tag_event":
                    push_tag_feed(e.get("tagger_name","?"), e.get("victim_name","?"))
                    if str(net.my_id) == e.get("victim_id"):
                        flash_alpha = 80
                        local_player.invul_frames = 90

        # ── Game logic ────────────────────────────────────────────────────
        time_left  = max(0, ROUND_TIME - (pygame.time.get_ticks() - round_start_ticks) // 1000)
        lava_active = (time_left <= 10)

        if current_game_state == "playing":
            local_player.update(keys, solids)

            # Slide emits a small shockwave once per slide
            if local_player.sliding and abs(local_player.vx) > 2.0 and tick % 15 == 0:
                local_player.outbound_events.append({
                    "type": "shockwave",
                    "cx": local_player.center[0],
                    "cy": local_player.center[1],
                    "r":  40,
                })

            # Tagger collision check
            if is_tagger and s_state:
                for p_id, p_data in s_state.get("players", {}).items():
                    if p_id == str(net.my_id): continue
                    r_rect = pygame.Rect(int(p_data["x"]), int(p_data["y"]), PLAYER_W, PLAYER_H)
                    if (local_player.rect.colliderect(r_rect)
                            and p_data["ghost"] == 0
                            and p_data["shield_up"] == 0
                            and p_data.get("invul_frames", 0) == 0):

                        # Combo bonus
                        if local_player.last_tagged_id == p_id:
                            local_player.combo_count += 1
                        else:
                            local_player.combo_count = 1
                            local_player.last_tagged_id = p_id

                        bonus = 2 if local_player.combo_count >= 2 else 0
                        # Last-second clutch bonus
                        clutch = 3 if time_left <= 2 else 0
                        scores[net.my_id] += 1 + bonus + clutch
                        tagger_age = 0

                        local_player.outbound_events.append({
                            "type":         "tag_event",
                            "tagger_name":  local_player.name,
                            "victim_name":  p_data.get("name", f"P{p_id}"),
                            "victim_id":    p_id,
                        })
                        flash_alpha = 80
                        net.send({"command": "round_over", "scores": scores})

            # Power-up pickup
            if s_state and s_state.get("level"):
                for idx, pu in enumerate(s_state["level"]["powerups"]):
                    if pu["alive"] and local_player.rect.colliderect(
                            pygame.Rect(pu["x"], pu["y"], 20, 20)):
                        kind = pu["kind"]
                        if kind == PU_JUMP:   local_player.jump_boost  = 300
                        elif kind == PU_SPEED: local_player.speed_boost = 360
                        elif kind == PU_GHOST: local_player.ghost       = 300
                        elif kind == PU_FREEZE: local_player.frozen     = 120
                        elif kind == PU_HEAVY: local_player.heavy       = 360
                        elif kind == PU_GRAV:  local_player.grav_flip   = 300
                        net.send({"command": "claim_powerup", "powerup_idx": idx})

            # Survival dividend: +1 point per 10 s alive as runner
            if not is_tagger and tick % 600 == 0:
                scores[net.my_id] += 1

            # Lava floor instant-tag
            if lava_active and not is_tagger:
                if local_player.on_ground and local_player.y + local_player.h >= GROUND_Y - 2:
                    scores[net.my_id] = max(0, scores[net.my_id] - 1)
                    net.send({"command": "round_over", "scores": scores})

            # Timer expired: host pushes round_over
            if time_left == 0 and net.my_id == 0:
                net.send({"command": "round_over", "scores": scores})

            net.send({
                "player_state": local_player.build_network_dict(),
                "events":       local_player.outbound_events,
            })
            local_player.outbound_events = []

        # ── Render ────────────────────────────────────────────────────────
        shake_x = random.randint(-camera_shake, camera_shake) if camera_shake > 0 else 0
        shake_y = random.randint(-camera_shake, camera_shake) if camera_shake > 0 else 0
        camera_shake = max(0, camera_shake - 1)

        screen.blit(bg_surf, (shake_x, shake_y))
        for sx, sy, br in stars:
            pygame.draw.circle(screen, (br,br,br), (sx+shake_x, sy+shake_y), 1)

        # Screen flash
        if flash_alpha > 0:
            fsurf = pygame.Surface((WIDTH, HEIGHT))
            fsurf.fill((255,255,255))
            fsurf.set_alpha(flash_alpha)
            screen.blit(fsurf, (0,0))
            flash_alpha = max(0, flash_alpha - 4)

        # ── HOME ──────────────────────────────────────────────────────────
        if current_game_state == "home":
            title = bigfont.render("ONLINE TAG !", True, (200, 80, 255))
            screen.blit(title, (WIDTH//2 - title.get_width()//2, 150))
            sub = font.render("[ PRESS SPACE TO CONNECT LOBBY ]", True, TEXT_COL)
            screen.blit(sub, (WIDTH//2 - sub.get_width()//2, HEIGHT//2))

        # ── PICK ──────────────────────────────────────────────────────────
        elif current_game_state == "pick":
            if not picker:
                picker = {"offers": random.sample(range(len(ABILITIES)), 3), "sel": 0}

            title = font.render("Choose Your Ability (WASD / Arrows + Jump)", True, TEXT_COL)
            screen.blit(title, (WIDTH//2 - title.get_width()//2, 50))

            for ci, ab_idx in enumerate(picker["offers"]):
                adef = ABILITIES[ab_idx]
                bx = WIDTH // 2 - 250 + ci * 180
                by = HEIGHT // 2 - 100
                bdr = (255,255,255) if picker["sel"] == ci else DIM_COL
                pygame.draw.rect(screen, (38, 33, 62), (bx, by, 140, 180), border_radius=10)
                pygame.draw.rect(screen, bdr,           (bx, by, 140, 180), 3, border_radius=10)
                icon_s = font.render(adef["icon"], True, adef["color"])
                screen.blit(icon_s, (bx + 60, by + 20))
                screen.blit(sm.render(adef["name"], True, TEXT_COL), (bx + 20, by + 70))
                screen.blit(sm.render(adef["desc"][:18], True, DIM_COL), (bx + 8, by + 95))

        # ── PLAYING / RESULT ──────────────────────────────────────────────
        elif current_game_state in ("playing", "result"):
            # Ground / lava
            lava_pulse  = lava_active and (tick // 15) % 2 == 0
            gnd_draw    = (200,40,10) if lava_pulse else ((180,30,0) if lava_active else GND_COL)
            gline_draw  = (255,80,0)  if lava_active else GND_LINE
            pygame.draw.rect(screen, gnd_draw,
                             pygame.Rect(shake_x, GROUND_Y+shake_y, WIDTH, HEIGHT-GROUND_Y))
            pygame.draw.line(screen, gline_draw,
                             (shake_x, GROUND_Y+shake_y), (WIDTH+shake_x, GROUND_Y+shake_y), 3)

            for w in walls:
                pygame.draw.rect(screen, WALL_COL,  w.move(shake_x,shake_y), border_radius=4)
                pygame.draw.rect(screen, WALL_EDGE,  w.move(shake_x,shake_y), 2, border_radius=4)
            for p in platforms:
                pygame.draw.rect(screen, PLAT_COL, p.move(shake_x,shake_y), border_radius=5)
                pygame.draw.rect(screen, PLAT_TOP,
                                 pygame.Rect(p.x+shake_x, p.y+shake_y, p.width, 4), border_radius=3)

            # Power-ups
            if s_state and s_state.get("level"):
                for pu in s_state["level"]["powerups"]:
                    if not pu["alive"]: continue
                    r = pygame.Rect(pu["x"]+shake_x, pu["y"]+shake_y, 20, 20)
                    pygame.draw.rect(screen, PU_COLORS[pu["kind"]], r, border_radius=5)
                    screen.blit(sm.render(PU_LABELS[pu["kind"]], True, (10,10,10)),
                                (pu["x"]+1+shake_x, pu["y"]+5+shake_y))

            # Players
            if s_state and "players" in s_state:
                for p_id, p_data in s_state["players"].items():
                    nd = local_player.build_network_dict() if p_id == str(net.my_id) else p_data
                    draw_network_player(screen, p_id, nd, (p_id == tagger_id),
                                        tick,
                                        tagger_age if p_id == tagger_id else 0,
                                        debug=DEBUG_MODE)

            # Tag feed
            update_draw_tag_feed(screen, sm)

            # Timer HUD
            timer_col = (255,80,40) if time_left <= 10 else TEXT_COL
            screen.blit(font.render(f"TIME: {time_left}s", True, timer_col),
                        (WIDTH//2 - 50, 15))

            if lava_active:
                warn = sm.render("!! LAVA FLOOR ACTIVE !!", True, (255,120,0))
                screen.blit(warn, (WIDTH//2 - warn.get_width()//2, 42))

            # Scores
            for idx, score in enumerate(scores):
                col = PLAYER_DEFS[idx][1]
                screen.blit(sm.render(f"{PLAYER_DEFS[idx][0]}: {score}", True, col),
                            (20 + idx*120, 20))

            # Debug bar
            if DEBUG_MODE:
                dbg = sm.render(
                    f"DEBUG | shake:{camera_shake} | tagger_age:{tagger_age} | invul:{local_player.invul_frames}",
                    True, (0,255,0))
                screen.blit(dbg, (8, HEIGHT-20))

            # Result overlay
            if current_game_state == "result":
                ov = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                ov.fill((0,0,0,150))
                screen.blit(ov, (0,0))

                msg = bigfont.render("ROUND OVER", True, CROWN_COL)
                screen.blit(msg, (WIDTH//2 - msg.get_width()//2, HEIGHT//2 - 80))

                hint = sm.render("Press SPACE for next ability pick & map", True, TEXT_COL)
                screen.blit(hint, (WIDTH//2 - hint.get_width()//2, HEIGHT//2 + 20))

                # Ability stats
                if local_player.ability_uses:
                    best = max(local_player.ability_uses.items(), key=lambda kv: kv[1])
                    stat = sm.render(f"You used [{best[0]}] x{best[1]} this session", True, DIM_COL)
                    screen.blit(stat, (WIDTH//2 - stat.get_width()//2, HEIGHT//2 + 50))

        pygame.display.flip()
        clock.tick(FPS)

if __name__ == "__main__":
    main()
