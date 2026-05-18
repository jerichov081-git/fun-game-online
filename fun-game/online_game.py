import pygame
import sys
import random
import math
import socket
import json
import threading

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

# Global font cache to prevent extreme frame-rate drops
BHOP_FONT = None

ABILITIES = [
    {"id": "rocket",     "name": "Rocket",  "color": (255, 140,  40), "icon": "R", "desc": "Launch yourself in your facing direction", "cd": 180},
    {"id": "blink",      "name": "Blink",   "color": (160,  80, 255), "icon": "B", "desc": "Teleport dash a short distance",           "cd": 150},
    {"id": "bomb",       "name": "Bomb",    "color": (255,  60,  60), "icon": "X", "desc": "Throw a bouncing bomb that explodes",      "cd": 240},
    {"id": "grapple",    "name": "Grapple", "color": (80,  220, 180), "icon": "G", "desc": "Hook onto the nearest surface",            "cd": 200},
    {"id": "shield",     "name": "Shield",  "color": (100, 180, 255), "icon": "S", "desc": "3s tag immunity + push nearby players",   "cd": 300},
    {"id": "slam_boost", "name": "Stomp+",  "color": (255, 200,  50), "icon": "*", "desc": "Ground slam shockwave is 2x larger (passive)", "cd": 0},
]

PU_JUMP, PU_SPEED, PU_FREEZE, PU_GHOST = "jump", "speed", "freeze", "ghost"
PU_COLORS = {PU_JUMP:(80,255,160), PU_SPEED:(255,195,40), PU_FREEZE:(80,200,255), PU_GHOST:(190,80,255)}
PU_LABELS = {PU_JUMP:"JMP", PU_SPEED:"SPD", PU_FREEZE:"FRZ", PU_GHOST:"GHO"}

# ─── Network Handler Class ────────────────────────────────────────────────────
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

# ─── Cosmestic Helpers ────────────────────────────────────────────────────────
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
        self.x, self.y, self.vx, self.vy, self.col, self.life, self.maxl, self.size = x, y, vx, vy, col, life, life, size
    def update(self):
        self.x += self.vx; self.y += self.vy; self.vy += 0.18; self.vx *= 0.97; self.life -= 1
    def draw(self, surface):
        a = max(0, int(255 * self.life / self.maxl))
        r = max(1, int(self.size * self.life / self.maxl))
        s = pygame.Surface((r * 2 + 1, r * 2 + 1), pygame.SRCALPHA)
        pygame.draw.circle(s, (*self.col, a), (r, r), r)
        surface.blit(s, (int(self.x) - r, int(self.y) - r))

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

# ─── Active Player Entity ─────────────────────────────────────────────────────
class Player:
    def __init__(self, x, y, color, controls, name):
        self.name, self.color, self.controls = name, color, controls
        self.x, self.y, self.vx, self.vy, self.w, self.h = float(x), float(y), 0.0, 0.0, PLAYER_W, PLAYER_H
        self.on_ground, self.on_wall, self.wall_normal, self.jumps_left = False, 0, 0, 2
        self.land_timer, self.ground_timer, self.bhop_mult, self.wall_jump_lock = 0, 0, 1.0, 0
        self.speed_boost, self.frozen, self.ghost, self.jump_boost = 0, 0, 0, 0
        self.slamming, self.slam_cd, self.slam_hit = False, 0, False
        self.ability_id, self.ability_cd, self.shield_up, self.facing = "none", 0, 0, 1
        self.squish, self.stretch = 0, 0
        self.trail, self.particles, self.sparks = [], [], []
        self.bombs = []
        self.grapple_obj = None
        self.outbound_events = []

    @property
    def rect(self): return pygame.Rect(int(self.x), int(self.y), self.w, self.h)
    @property
    def center(self): return (self.x + self.w / 2, self.y + self.h / 2)

    def run_speed(self):
        s = BASE_SPEED * self.bhop_mult
        if self.speed_boost > 0: s *= 1.45
        return s

    def use_ability(self, solids):
        if self.ability_id in ("none", "slam_boost") or self.ability_cd > 0 or self.frozen > 0: return
        adef = next((a for a in ABILITIES if a["id"] == self.ability_id), None)
        if not adef: return

        if self.ability_id == "rocket":
            self.vx = self.facing * 16.0
            self.vy = -5.0
            self.ability_cd = adef["cd"]
        elif self.ability_id == "blink":
            nx = max(0, min(WIDTH - self.w, self.x + self.facing * 160))
            if not any(pygame.Rect(int(nx), int(self.y), self.w, self.h).colliderect(s) for s in solids):
                self.x = nx
                self.ability_cd = adef["cd"]
        elif self.ability_id == "bomb":
            self.bombs.append({"x": self.x+self.w/2, "y": self.y, "vx": self.facing*7.0+self.vx*0.3, "vy": -5.0, "fuse": 180})
            self.ability_cd = adef["cd"]
        elif self.ability_id == "grapple":
            if not self.grapple_obj:
                self.grapple_obj = {"x": self.x+self.w/2, "y": self.y+self.h/2, "vx": self.facing*18.0, "vy": -4.0, "attached": False, "ax": 0, "ay":0, "life": 40}
                self.ability_cd = adef["cd"]
        elif self.ability_id == "shield":
            self.shield_up = 180
            self.ability_cd = adef["cd"]
            self.outbound_events.append({"type": "shield_push", "cx": self.center[0], "cy": self.center[1]})

    def update(self, keys, solids):
        if self.frozen == 0:
            left, right = keys[self.controls["left"]], keys[self.controls["right"]]
            wish = (1 if right else 0) - (1 if left else 0)
            if wish != 0: self.facing = wish
            if not self.slamming:
                target = self.run_speed() * wish
                accel = ACCEL if self.on_ground else AIR_ACCEL
                if wish > 0: self.vx = min(self.vx + accel, target) if self.vx < target else self.vx
                elif wish < 0: self.vx = max(self.vx - accel, target) if self.vx > target else self.vx
                else: self.vx *= (FRICTION if self.on_ground else AIR_FRICTION)
        else:
            self.vx *= 0.72

        if self.on_wall != 0 and not self.on_ground and self.vy > WALL_SLIDE_VEL and not self.slamming:
            self.vy = WALL_SLIDE_VEL

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

        self.vy = min(self.vy + GRAVITY, MAX_FALL)
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

        self.y += self.vy
        prev_ground = self.on_ground
        self.on_ground = False
        py = self.rect
        for solid in solids:
            if not py.colliderect(solid): continue
            if self.vy >= 0:
                if (int(self.y) - int(self.vy)) <= solid.top + 4:
                    self.y = solid.top - self.h
                    self.vy = 0
                    self.on_ground = True
                    self.on_wall = 0
                    if not prev_ground:
                        self.squish = 7
                        self.land_timer = BHOP_WINDOW
                        self.ground_timer = 0
                    if self.slamming and not self.slam_hit:
                        self.slam_hit = True
                        self.slamming = False
                        radius = SLAM_SHOCKWAVE_R * (2 if self.ability_id == "slam_boost" else 1)
                        self.outbound_events.append({"type": "shockwave", "cx": self.center[0], "cy": self.y + self.h, "r": radius})
                        self.slam_cd = 45
                    else:
                        self.slamming = False
                    self.jumps_left = 2
            elif self.vy < 0:
                if (int(self.y) - int(self.vy)) >= solid.bottom - 4:
                    self.y = solid.bottom
                    self.vy = 0
            py = self.rect

        if self.on_ground:
            self.ground_timer += 1
            if self.ground_timer > BHOP_DECAY_DELAY: self.bhop_mult = max(1.0, self.bhop_mult * BHOP_DECAY_RATE)
        else:
            self.bhop_mult = max(1.0, self.bhop_mult * 0.998)

        if self.grapple_obj:
            g = self.grapple_obj
            if not g["attached"]:
                g["life"] -= 1
                if g["life"] <= 0: self.grapple_obj = None
                else:
                    g["vy"] += 0.3; g["x"] += g["vx"]; g["y"] += g["vy"]
                    gr = pygame.Rect(int(g["x"])-4, int(g["y"])-4, 8, 8)
                    for s in solids:
                        if gr.colliderect(s): g["attached"] = True; g["ax"] = g["x"]; g["ay"] = g["y"]; break
                    if g["x"] < 0 or g["x"] > WIDTH or g["y"] < 0 or g["y"] > HEIGHT: self.grapple_obj = None

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
                    elif b["vy"] < 0: b["y"] = s.bottom + 8; b["vy"] = -b["vy"] * 0.5
                    else: b["vx"] = -b["vx"] * 0.7
            rem_bombs.append(b)
        self.bombs = rem_bombs

        for attr in ("speed_boost", "frozen", "ghost", "jump_boost", "ability_cd", "slam_cd", "shield_up", "squish", "stretch", "land_timer", "wall_jump_lock"):
            v = getattr(self, attr)
            if v > 0: setattr(self, attr, v - 1)

    def jump(self):
        if self.frozen or self.slamming: return
        if self.on_wall != 0 and not self.on_ground:
            self.vx = self.wall_normal * WALLJUMP_X; self.vy = WALLJUMP_Y
            self.on_wall = 0; self.wall_jump_lock = 14; self.stretch = 10; return
        if self.land_timer > 0: self.bhop_mult = min(MAX_BHOP_MULT, self.bhop_mult * BHOP_BOOST); self.land_timer = 0
        if self.jumps_left > 0:
            self.vy = JUMP_POWER * (1.20 if self.jump_boost > 0 else 1.0)
            self.jumps_left -= 1; self.on_ground = False; self.stretch = 10

    def slam(self):
        if self.on_ground or self.slam_cd > 0 or self.frozen or self.slamming: return
        self.slamming = True; self.vy = SLAM_VEL; self.vx *= 0.3; self.slam_hit = False

    def build_network_dict(self):
        return {
            "name": self.name, "x": self.x, "y": self.y, "vx": self.vx, "vy": self.vy,
            "facing": self.facing, "squish": self.squish, "stretch": self.stretch,
            "shield_up": self.shield_up, "ghost": self.ghost, "frozen": self.frozen,
            "slamming": self.slamming, "ability_id": self.ability_id, "ability_cd": self.ability_cd,
            "bhop_mult": self.bhop_mult, "bombs": [{"x":b["x"], "y":b["y"], "fuse":b["fuse"]} for b in self.bombs],
            "grapple": self.grapple_obj
        }

# ─── Remote Player Draw Replica ───────────────────────────────────────────────
def draw_network_player(surface, p_id, data, is_tagger, tick):
    x, y, w, h = data["x"], data["y"], PLAYER_W, PLAYER_H
    col = PLAYER_DEFS[int(p_id)][1]
    
    if data["shield_up"] > 0: col = lerp_color(col, (100, 180, 255), 0.6)
    if data["ghost"] > 0: col = lerp_color(col, (190, 80, 255), 0.5)
    if data["frozen"] > 0: col = lerp_color(col, (120, 210, 255), 0.7)

    dw, dh = w, h
    if data["squish"] > 0:
        dw, dh = int(w * (1 + 0.26 * (data["squish"]/7))), int(h * (1 - 0.20 * (data["squish"]/7)))
    elif data["stretch"] > 0:
        dw, dh = int(w * (1 - 0.16 * (data["stretch"]/10))), int(h * (1 + 0.28 * (data["stretch"]/10)))

    dx = int(x) + w // 2 - dw // 2
    dy = int(y) + h - dh

    if is_tagger:
        gr = dw // 2 + 13 + int(4 * math.sin(tick * 0.18))
        gsurf = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
        pygame.draw.circle(gsurf, (*CROWN_COL, 48), (gr, gr), gr)
        surface.blit(gsurf, (dx + dw // 2 - gr, dy + dh // 2 - gr))

    pygame.draw.rect(surface, col, pygame.Rect(dx, dy, dw, dh), border_radius=8)

    ey = dy + dh // 3
    facing = data["facing"]
    e1x, e2x = (dx + dw * 2 // 5, dx + dw * 4 // 5 - 4) if facing > 0 else (dx + dw // 5, dx + dw * 3 // 5 - 4)
    for ex in (e1x, e2x):
        pygame.draw.circle(surface, (255, 255, 255), (ex, ey), 4)
        pygame.draw.circle(surface, (12, 8, 22), (ex + facing, ey + 1), 2)

    if is_tagger:
        cx, cyt = dx + dw // 2, dy - 4
        pygame.draw.polygon(surface, CROWN_COL, [(cx-10,cyt),(cx-5,cyt-9),(cx,cyt-4),(cx+5,cyt-9),(cx+10,cyt)])

    for b in data.get("bombs", []):
        ClientBomb(b["x"], b["y"], b["fuse"]).draw(surface, tick)
    if data.get("grapple"):
        g = data["grapple"]
        ClientGrapple(g["x"], g["y"], g["attached"], g["ax"], g["ay"]).draw(surface, x+w/2, y+h/2)

    # Uses the performance optimized global font cache
    if data.get("bhop_mult", 1.0) > 1.08 and BHOP_FONT:
        st = BHOP_FONT.render(f"x{data['bhop_mult']:.1f}", True, (255, 220, 60))
        surface.blit(st, (dx, dy - 22))

# ─── Network Main Integration ──────────────────────────────────────────────────
def main():
    pygame.init()
    global BHOP_FONT
    
    server_ip = input("Enter Server IP (Press Enter for Localhost): ").strip()
    if not server_ip: server_ip = "127.0.0.1"

    net = NetworkClient(server_ip=server_ip)
    if not net.connect():
        print("Could not connect to online server.")
        return

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(f"TAG! Online — Slot Player {net.my_id}")
    clock = pygame.time.Clock()

    bigfont = pygame.font.SysFont("Consolas", 34, bold=True)
    font = pygame.font.SysFont("Consolas", 24, bold=True)
    sm = pygame.font.SysFont("Consolas", 14)
    BHOP_FONT = pygame.font.SysFont("Consolas", 11, bold=True) # Initialized ONCE here

    bg_surf = make_bg(WIDTH, HEIGHT)
    stars = [(random.randint(0, WIDTH), random.randint(0, HEIGHT * 2 // 3), random.randint(55, 185)) for _ in range(100)]
    
    # Track the active layout dynamically
    loaded_level = net.level_layout
    solids = [GROUND_RECT]
    platforms = [pygame.Rect(*p) for p in loaded_level["platforms"]]
    walls = [pygame.Rect(*w) for w in loaded_level["walls"]]
    solids.extend(platforms + walls)

    p_def = PLAYER_DEFS[net.my_id]
    local_player = Player(400, 100, p_def[1], p_def[2], f"{p_def[0]} (You)")
    
    tick = 0
    round_start_ticks = pygame.time.get_ticks()
    picker = None
    last_game_state = None

    while True:
        tick += 1
        keys = pygame.key.get_pressed()
        s_state = net.latest_server_state

        current_game_state = s_state["game_state"] if s_state else "home"
        tagger_id = str(s_state["tagger_idx"]) if s_state else "0"
        scores = s_state["scores"] if s_state else [0,0,0,0]

        # FIX 1: Dynamically update map blocks and bounding rects when server switches levels
        if s_state and s_state.get("level") != loaded_level:
            loaded_level = s_state["level"]
            platforms = [pygame.Rect(*p) for p in loaded_level["platforms"]]
            walls = [pygame.Rect(*w) for w in loaded_level["walls"]]
            solids = [GROUND_RECT] + platforms + walls

        # FIX 4: Intercept State transitions to keep round clocks and pick menus reset for all clients
        if current_game_state != last_game_state:
            if current_game_state in ("pick", "playing"):
                round_start_ticks = pygame.time.get_ticks()
            if current_game_state == "pick":
                picker = None
            last_game_state = current_game_state

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit(); sys.exit()
                
                if current_game_state == "home" and event.key == pygame.K_SPACE:
                    net.send({"command": "start_game"})
                
                if current_game_state == "pick" and picker:
                    if event.key == local_player.controls["left"]: picker["sel"] = (picker["sel"]-1)%3
                    if event.key == local_player.controls["right"]: picker["sel"] = (picker["sel"]+1)%3
                    if event.key == local_player.controls["up"]:
                        local_player.ability_id = ABILITIES[picker["offers"][picker["sel"]]]["id"]
                        net.send({"command": "abilities_chosen"})

                if current_game_state == "playing":
                    if event.key == local_player.controls["up"]: local_player.jump()
                    if event.key == local_player.controls["down"]: local_player.slam()
                    if event.key == local_player.controls["ability"]: local_player.use_ability(solids)
                
                if current_game_state == "result" and event.key == pygame.K_SPACE:
                    net.send({"command": "next_round"})

        if s_state and s_state.get("events"):
            for e in s_state["events"]:
                cx, cy = e.get("cx", 0), e.get("cy", 0)
                dx, dy = local_player.center[0] - cx, local_player.center[1] - cy
                dist = math.sqrt(dx**2 + dy**2) + 0.01
                
                if e["type"] == "shockwave" and dist < e["r"]:
                    if local_player.frozen == 0 and local_player.shield_up == 0:
                        force = 1.0 - dist / e["r"]
                        local_player.vx += (dx / dist) * SLAM_KNOCKBACK * force
                        local_player.vy += SLAM_UPKICK * force
                elif e["type"] == "bomb_explosion" and dist < 90:
                    force = 1.0 - dist / 90
                    local_player.vx += (dx / dist) * 12 * force
                    local_player.vy = min(local_player.vy, -8 * force)
                elif e["type"] == "shield_push" and dist < 100:
                    local_player.vx += dx / dist * 10
                    local_player.vy += dy / dist * 10 - 4

        # ─── Game Loop Calculations ───────────────────────────────────────────
        if current_game_state == "playing":
            local_player.update(keys, solids)
            
            if tagger_id == str(net.my_id):
                for p_id, p_data in s_state.get("players", {}).items():
                    if p_id == str(net.my_id): continue
                    r_rect = pygame.Rect(int(p_data["x"]), int(p_data["y"]), PLAYER_W, PLAYER_H)
                    if local_player.rect.colliderect(r_rect) and p_data["ghost"] == 0 and p_data["shield_up"] == 0:
                        scores[net.my_id] += 1
                        net.send({"command": "round_over", "scores": scores})

            # FIX 3: Detect local power-up overlaps and tell the server to deactivate it globally
            if s_state and s_state.get("level"):
                for idx, pu in enumerate(s_state["level"]["powerups"]):
                    if pu["alive"] and local_player.rect.colliderect(pygame.Rect(pu["x"], pu["y"], 20, 20)):
                        if pu["kind"] == "jump": local_player.jump_boost = 300
                        elif pu["kind"] == "speed": local_player.speed_boost = 360
                        elif pu["kind"] == "ghost": local_player.ghost = 300
                        elif pu["kind"] == "freeze": local_player.frozen = 120
                        net.send({"command": "claim_powerup", "powerup_idx": idx})

            net.send({
                "player_state": local_player.build_network_dict(),
                "events": local_player.outbound_events
            })
            local_player.outbound_events = []

        # ─── Render Pipeline ──────────────────────────────────────────────────
        screen.blit(bg_surf, (0,0))
        for sx, sy, br in stars: pygame.draw.circle(screen, (br, br, br), (sx, sy), 1)

        if current_game_state == "home":
            title = bigfont.render("ONLINE TAG !", True, (200, 80, 255))
            screen.blit(title, (WIDTH//2 - title.get_width()//2, 150))
            sub = font.render("[ PRESS SPACE TO CONNECT LOBBY ]", True, TEXT_COL)
            screen.blit(sub, (WIDTH//2 - sub.get_width()//2, HEIGHT//2))

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
                pygame.draw.rect(screen, bdr, (bx, by, 140, 180), 3, border_radius=10)
                screen.blit(font.render(adef["icon"], True, TEXT_COL), (bx+60, by+20))
                screen.blit(sm.render(adef["name"], True, TEXT_COL), (bx+20, by+70))

        elif current_game_state in ("playing", "result"):
            pygame.draw.rect(screen, GND_COL, GROUND_RECT)
            pygame.draw.line(screen, GND_LINE, (0, GROUND_Y), (WIDTH, GROUND_Y), 3)

            for w in walls:
                pygame.draw.rect(screen, WALL_COL, w, border_radius=4)
                pygame.draw.rect(screen, WALL_EDGE, w, 2, border_radius=4)
            for p in platforms:
                pygame.draw.rect(screen, PLAT_COL, p, border_radius=5)
                pygame.draw.rect(screen, PLAT_TOP, pygame.Rect(p.x, p.y, p.width, 4), border_radius=3)

            if s_state and s_state.get("level"):
                for pu in s_state["level"]["powerups"]:
                    if not pu["alive"]: continue
                    r = pygame.Rect(pu["x"], pu["y"], 20, 20)
                    pygame.draw.rect(screen, PU_COLORS[pu["kind"]], r, border_radius=5)
                    screen.blit(sm.render(PU_LABELS[pu["kind"]], True, (10,10,10)), (pu["x"]+1, pu["y"]+5))

            if s_state and "players" in s_state:
                for p_id, p_data in s_state["players"].items():
                    if p_id == str(net.my_id):
                        draw_network_player(screen, p_id, local_player.build_network_dict(), (p_id == tagger_id), tick)
                    else:
                        draw_network_player(screen, p_id, p_data, (p_id == tagger_id), tick)

            # HUD Display Rendering
            time_left = max(0, ROUND_TIME - (pygame.time.get_ticks() - round_start_ticks) // 1000)
            screen.blit(font.render(f"TIME: {time_left}s", True, TEXT_COL), (WIDTH//2 - 50, 15))
            
            # FIX: Trigger round end if the timer runs dry (Host slot verifies and pushes it)
            if current_game_state == "playing" and time_left == 0 and net.my_id == 0:
                net.send({"command": "round_over", "scores": scores})
            
            for idx, score in enumerate(scores):
                p_name = PLAYER_DEFS[idx][0]
                col = PLAYER_DEFS[idx][1]
                screen.blit(sm.render(f"{p_name}: {score}", True, col), (20 + idx*120, 20))

            if current_game_state == "result":
                pygame.draw.rect(screen, (0,0,0,180), (0,0,WIDTH,HEIGHT))
                msg = bigfont.render("ROUND OVER", True, CROWN_COL)
                screen.blit(msg, (WIDTH//2 - msg.get_width()//2, HEIGHT//2 - 50))
                hint = sm.render("Press SPACE to transition pick stage maps layout", True, TEXT_COL)
                screen.blit(hint, (WIDTH//2 - hint.get_width()//2, HEIGHT//2 + 20))

        pygame.display.flip()
        clock.tick(FPS)

if __name__ == "__main__":
    main()
