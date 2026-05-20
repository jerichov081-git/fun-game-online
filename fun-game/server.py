import socket
import threading
import json
import random
import os

# Prevent Pygame from opening a window on the server machine
os.environ["SDL_VIDEODRIVER"] = "dummy"
import pygame

WIDTH, HEIGHT = 960, 620
GROUND_Y = HEIGHT - 50
PLAT_H = 14
WALL_W = 14

def generate_level_data():
    """Generates the level layout on the server so all clients share the same map."""
    platforms, walls = [], []
    cols = 6
    col_w = WIDTH // cols
    bands = [
        (GROUND_Y - 95,  GROUND_Y - 125),
        (GROUND_Y - 185, GROUND_Y - 230),
        (GROUND_Y - 280, GROUND_Y - 340),
        (GROUND_Y - 375, GROUND_Y - 440),
    ]
    used = set()
    attempts = 0
    while len(platforms) < 11 and attempts < 300:
        attempts += 1
        col = random.randint(0, cols - 1)
        band = random.choice(bands)
        key = (col, band[0])
        if key in used: continue
        used.add(key)
        pw = random.randint(110, 175)
        x = col * col_w + random.randint(0, max(0, col_w - pw))
        x = max(0, min(WIDTH - pw, x))
        y = random.randint(band[1], band[0])
        platforms.append([x, y, pw, PLAT_H])

    for _ in range(random.randint(3, 5)):
        for _att in range(40):
            wh = random.randint(90, 165)
            wx = random.randint(60, WIDTH - 60 - WALL_W)
            ay = random.choice([GROUND_Y - 70, GROUND_Y - 165, GROUND_Y - 270, GROUND_Y - 375])
            wy = ay - wh
            
            # Simulated collision checking
            wr = pygame.Rect(wx, wy, WALL_W, wh)
            p_rects = [pygame.Rect(*p) for p in platforms]
            w_rects = [pygame.Rect(*w) for w in walls]
            if (not any(wr.inflate(24, 12).colliderect(p) for p in p_rects) and
                    not any(wr.inflate(12, 0).colliderect(w) for w in w_rects)):
                walls.append([wx, wy, WALL_W, wh])
                break
                
    # Sync floor power-ups
    powerups = []
    kinds = ["jump", "speed", "freeze", "ghost"]
    chosen_plats = random.sample(platforms, min(len(platforms), 4))
    for p in chosen_plats:
        kind = random.choice(kinds)
        px = p[0] + p[2] // 2 - 10
        py = p[1] - 22
        powerups.append({"x": px, "y": py, "kind": kind, "alive": True})

    return {"platforms": platforms, "walls": walls, "powerups": powerups}

class TagServer:
    def __init__(self, host="0.0.0.0", port=5555):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Bypasses WinError 10048 if port was recently closed
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        self.server.bind((host, port))
        self.server.listen(4)
        self.clients = {}
        self.global_state = {
            "game_state": "home",  # home, pick, playing, result
            "players": {},
            "level": generate_level_data(),
            "tagger_idx": 0,
            "scores": [0, 0, 0, 0],
            "events": []
        }
        
        hosting_ip = self.get_local_ip()
        
        print("=" * 65)
        print(f"[SERVER STARTED] Listening on port {port}...")
        print(f"[JOIN INFO] Play on LAN using IP address: {hosting_ip}")
        print("=" * 65)

    def get_local_ip(self):
        """Discovers the active local network IP adapter interface."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        finally:
            s.close()
        return ip

    def broadcast(self, data):
        """Send snapshot payloads out to all connected clients."""
        msg = json.dumps(data) + "\n"
        encoded = msg.encode()
        for client_socket in list(self.clients.values()):
            try:
                client_socket.sendall(encoded)
            except:
                pass

    def handle_client(self, client_socket, player_id):
        print(f"[CONNECTION] Handshaking securely with Player {player_id}...")
        init_payload = {"player_id": player_id, "level": self.global_state["level"]}
        try:
            client_socket.sendall((json.dumps(init_payload) + "\n").encode())
            print(f"[SUCCESS] Map layout sent to Player {player_id} configuration.")
        except Exception as e:
            print(f"[ERROR] Handshake failed for Player {player_id}: {e}")
            client_socket.close()
            return

        buffer = ""
        while True:
            try:
                data = client_socket.recv(4096).decode()
                if not data: break
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if not line.strip(): continue
                    
                    try:
                        packet = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    if "player_state" in packet:
                        self.global_state["players"][str(player_id)] = packet["player_state"]
                    
                    if "command" in packet:
                        cmd = packet["command"]
                        if cmd == "start_game":
                            self.global_state["game_state"] = "pick"
                        elif cmd == "abilities_chosen":
                            self.global_state["game_state"] = "playing"
                            active_ids = list(self.clients.keys())
                            if active_ids:
                                self.global_state["tagger_idx"] = random.choice(active_ids)
                        elif cmd == "round_over":
                            self.global_state["game_state"] = "result"
                            self.global_state["scores"] = packet["scores"]
                        elif cmd == "next_round":
                            self.global_state["level"] = generate_level_data()
                            self.global_state["game_state"] = "pick"
                        
                    if "events" in packet:
                        self.global_state["events"].extend(packet["events"])

                self.broadcast(self.global_state)
                self.global_state["events"] = [] 
            except Exception as e:
                print(f"[ERROR] Connection broken with Player {player_id}: {e}")
                break

        print(f"[DISCONNECT] Player {player_id} left.")
        if str(player_id) in self.global_state["players"]:
            del self.global_state["players"][str(player_id)]
        if player_id in self.clients:
            del self.clients[player_id]
        client_socket.close()

    def run(self):
        player_counter = 0
        while True:
            try:
                client_socket, addr = self.server.accept()
                if len(self.clients) >= 4:
                    client_socket.close()
                    continue
                
                assigned_id = player_counter % 4
                player_counter += 1
                
                self.clients[assigned_id] = client_socket
                print(f"[CONNECTED] Incoming player from network address {addr}")
                threading.Thread(target=self.handle_client, args=(client_socket, assigned_id), daemon=True).start()
            except Exception as e:
                print(f"[SERVER CRASH ALERT] Error accepting pipeline connection: {e}")
                break

if __name__ == "__main__":
    server = TagServer()
    server.run()
