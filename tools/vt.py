"""Minimal VT renderer: replays CUP/ED/EL/SGR onto a grid so framed
terminal output can be inspected as plain text in a non-interactive shell."""
import re, sys

def render(data: str, cols=80, rows=24) -> str:
    grid = [[" "] * cols for _ in range(rows)]
    cy = cx = 0
    i = 0
    while i < len(data):
        ch = data[i]
        if ch == "\x1b" and i + 1 < len(data) and data[i+1] in "()#":
            i += 3; continue
        if ch == "\x1b" and i + 1 < len(data) and data[i+1] in "=>":
            i += 2; continue
        if ch == "\x1b" and i + 1 < len(data) and data[i+1] == "[":
            m = re.match(r"\x1b\[([0-9;?]*)([A-Za-z])", data[i:])
            if not m:
                i += 1; continue
            params, cmd = m.group(1), m.group(2)
            nums = [int(p) for p in params.split(";") if p.isdigit()]
            if cmd == "H":
                cy = (nums[0] - 1) if nums else 0
                cx = (nums[1] - 1) if len(nums) > 1 else 0
            elif cmd == "J":
                if not nums or nums[0] == 2:
                    grid = [[" "] * cols for _ in range(rows)]; cy = cx = 0
            elif cmd == "A": cy = max(0, cy - (nums[0] if nums else 1))
            elif cmd == "B": cy = min(rows - 1, cy + (nums[0] if nums else 1))
            elif cmd == "C": cx = min(cols - 1, cx + (nums[0] if nums else 1))
            elif cmd == "D": cx = max(0, cx - (nums[0] if nums else 1))
            elif cmd == "d": cy = (nums[0] - 1) if nums else 0
            elif cmd == "G": cx = (nums[0] - 1) if nums else 0
            elif cmd == "X":      # ECH: erase n chars at the cursor, no move
                n = nums[0] if nums else 1
                for x in range(cx, min(cols, cx + n)): grid[cy][x] = " "
            elif cmd == "P":      # DCH: delete n chars, shifting left
                n = nums[0] if nums else 1
                row = grid[cy][:cx] + grid[cy][cx+n:] + [" "] * n
                grid[cy] = row[:cols]
            elif cmd == "@":      # ICH: insert n blanks, shifting right
                n = nums[0] if nums else 1
                row = grid[cy][:cx] + [" "] * n + grid[cy][cx:]
                grid[cy] = row[:cols]
            elif cmd == "L":      # IL: insert n blank lines
                n = nums[0] if nums else 1
                for _ in range(n):
                    grid.insert(cy, [" "] * cols); grid.pop()
            elif cmd == "M":      # DL: delete n lines
                n = nums[0] if nums else 1
                for _ in range(n):
                    grid.pop(cy); grid.append([" "] * cols)
            elif cmd == "K":
                for x in range(cx, cols): grid[cy][x] = " "
            i += m.end(); continue
        if ch == "\n":
            cy += 1; cx = 0; i += 1; continue
        if ch == "\r":
            cx = 0; i += 1; continue
        if 0 <= cy < rows and 0 <= cx < cols and ch.isprintable():
            grid[cy][cx] = ch
        cx += 1
        if cx >= cols: cx = 0; cy += 1
        i += 1
    return "\n".join("".join(r).rstrip() for r in grid)

if __name__ == "__main__":
    print(render(sys.stdin.read(), int(sys.argv[1]), int(sys.argv[2])))
