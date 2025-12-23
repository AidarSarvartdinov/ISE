from io import StringIO

class LimitedStream(StringIO):
    """Custom wrapper for StringIO to prevent large output"""
    def __init__(self, limit_chars=1024):
        super().__init__()
        self.limit_chars = limit_chars
        self.current_chars = 0
        self.truncated = False

    def write(self, text):
        # if the limit is reached, exit
        if self.truncated:
            return len(text)
        
        # check if a new piece of text will fit
        if self.current_chars + len(text) <= self.limit_chars:
            super().write(text)
            self.current_chars += len(text)
            return len(text)

        # calculate how much more can be added
        remaining = self.limit_chars - self.current_chars

        if remaining > 0:
            # add the piece that fits
            super().write(text[:remaining])
            self.current_chars += remaining

        if not self.truncated:
            # add a mark
            super().write("\n--- OUTPUT TRUNCATED ---")
            self.truncated = True

        return len(text)
