# Works Cited:
# 
# http://www.music.mcgill.ca/~ich/classes/mumt306/StandardMIDIfileformat.html
# https://github.com/colxi/midi-parser-js/wiki/MIDI-File-Format-Specifications

import copy
import time


class MIDIError(Exception):
    """Generic exception for errors reading a MIDI file."""
    pass


class MidiFile():
    """
    Represents a .mid file as an object.
    
    Contains header information and at least one MidiTrack.
    """
    def __init__(self, f):
        header = f.read(4)
        assert header == b'MThd'
        self._length = int.from_bytes(f.read(4), byteorder="big")
        assert self._length >= 6
        self.format = int.from_bytes(f.read(2), byteorder="big")
        self._num_tracks = int.from_bytes(f.read(2), byteorder="big")
        self._division = int.from_bytes(f.read(2), byteorder="big")
        self.division_type = self._division >> 15 & 1
        if self.division_type == 1:
            raise MIDIError("That file determines time using seconds instead of beats, and doing math with time is hard.")
        self.per_quarter_note = self._division & 0b11111111111111
        # Flush out extra header info we don't support
        self._trailing = bytes(0)
        if self._length > 6:
            self._trailing = f.read(self._length - 6)
        self.tracks = [MidiTrack(f) for x in range(self._num_tracks)]
    
    def to_file(self):
        """Converts this file and all of its tracks into bytes data."""
        result = (
            b'MThd'
            + self._length.to_bytes(4, byteorder="big")
            + self.format.to_bytes(2, byteorder="big")
            + self._num_tracks.to_bytes(2, byteorder="big")
            + self._division.to_bytes(2, byteorder="big")
            + self._trailing
        )
        for track in self.tracks:
            result += track.to_file()
        return result

    def __repr__(self):
        """Pretty print this object for debugging."""
        return f"MidiFile(per_quarter_note={self.per_quarter_note}, tracks={self.tracks})"


class MidiTrack():
    """
    Represents a track in a .mid file as an object.
    
    Contains at least one MidiEvent.
    """
    def __init__(self, f):
        header = f.read(4)
        assert header == b'MTrk'
        self.events = []
        length = int.from_bytes(f.read(4), byteorder="big")
        while length:
            event = MidiEvent(f)
            self.events.append(event)
            length -= event._length
    
    def to_file(self):
        """Converts this track and all of its events into bytes data."""
        result = bytes(0)
        for event in self.events:
            result += event.to_file()
        result = (
            b'MTrk'
            + len(result).to_bytes(4, byteorder="big")
            + result
        )
        return result
    
    def __repr__(self):
        """Pretty print this object for debugging."""
        return f"MidiTrack(events={self.events})"


class MidiEvent():
    """
    Represents an event in a .mid file as an object.
    
    Contains some kind of information, ex. a note being pushed.
    """
    def __init__(self, f):
        self._length = 0 # only use in track __init__
        self.timedelta = 0
        self.note = None
        self.velocity = None
        self.channel = None
        self._trailing_ignore = bytes(0)
        # Handle variable int
        while True:
            self.timedelta = self.timedelta << 7
            raw = int.from_bytes(self._read_bytes(f, 1), byteorder="big")
            self.timedelta += (raw & 0b1111111)
            if not raw >> 7 & 1:
                break
        # Figure out the event to process it
        self._event_info = int.from_bytes(self._read_bytes(f, 1), byteorder="big")
        event_type = self._event_info >> 4
        if event_type == 0xF:
            event_subtype = self._event_info & 0b1111
            # This event has extra stuff to ignore
            if event_subtype == 0xF:
                # Ignore meta event type
                self._trailing_ignore += self._read_bytes(f, 1)
            # Figure out how much to ignore
            ignore_num = 0
            while True:
                ignore_raw = self._read_bytes(f, 1)
                self._trailing_ignore += ignore_raw
                ignore_raw = int.from_bytes(ignore_raw, byteorder="big")
                ignore_num += ignore_raw & 0b1111111
                if not ignore_raw >> 7 & 1:
                    break
            self._trailing_ignore += self._read_bytes(f, ignore_num)
        elif event_type in (0xA, 0xB, 0xE):
            self._trailing_ignore += self._read_bytes(f, 2)
        elif event_type in (0xC, 0xD):
            self._trailing_ignore += self._read_bytes(f, 1)
        elif event_type in (0x8, 0x9):
            self.channel = self._event_info & 0b1111
            self.note = int.from_bytes(self._read_bytes(f, 1), byteorder="big")
            self.velocity = int.from_bytes(self._read_bytes(f, 1), byteorder="big")
        else:
            raise MIDIError("That file has an invalid MIDI event type, and I couldn't figure out how to ignore those as indicated in the filetype spec.")
    
    def _read_bytes(self, f, number):
        """
        Helper to read some number of bytes while updating 
        the internal counter of the number of bytes read.
        """
        self._length += number
        return f.read(number)
    
    def to_file(self):
        """Converts this event into bytes data."""
        td = self.timedelta
        result = bytes(0)
        is_first = True
        while td:
            next_byte = td & 0b1111111
            if not is_first:
                next_byte = next_byte | 0b10000000
            is_first = False
            td = td >> 7
            result = next_byte.to_bytes(1, byteorder="big") + result
        
        if len(result) == 0:
            result = bytes(1)
        
        result += self._event_info.to_bytes(1, byteorder="big")
        if self.note is not None:
            result += self.note.to_bytes(1, byteorder="big")
            result += self.velocity.to_bytes(1, byteorder="big")
        result += self._trailing_ignore
        return result

    def __repr__(self):
        """Pretty print this object for debugging."""
        return f"MidiEvent(timedelta={self.timedelta}, note={self.note}, velocity={self.velocity})"


def pitch(midi, tracks):
    """Modifies the pitch of all notes in a midi file."""
    while True:
        print(
            "Enter a signed integer denoting the change in pitch in half steps.\n"
            "Positive ints raise the pitch, negative ones lower the pitch.\n"
            "Remember, a multiple of 12 will raise/lower by octaves.\n\n"
            "Enter \"b\" to select a different effect.\n"
        )
        amount = input(">")
        if amount == "b":
            break
        try:
            amount = int(amount)
        except ValueError:
            print("That is not a valid option.")
            continue
        for track in tracks:
            for event in track.events:
                if event.note is None:
                    continue
                event.note = max(0, min(127, event.note + amount))
        print("Pitch shift applied.")
        break
        

def velocity(midi, tracks):
    """Modifies the velocity of all notes in a midi file."""
    while True:
        print(
            "Enter an integer denoting the velocity.\n"
            "This value should be between 1 and 127.\n\n"
            "Enter \"b\" to select a different effect.\n"
        )
        amount = input(">")
        if amount == "b":
            break
        try:
            amount = int(amount)
        except ValueError:
            print("That is not a valid option.")
            continue
        if amount < 1 or 127 < amount:
            print("The velocity value must be between 1 and 127.")
            continue
        for track in tracks:
            for event in track.events:
                if not event.velocity:
                    continue
                event.velocity = amount
        print("Velocity applied.")
        break


def chorus(midi, tracks):
    """Adds a chorus effect to all notes in a midi file."""
    while True:
        print(
            "Enter a series of signed integers seperated by commas denoting the relative pitches in half steps to add.\n"
            "Positive ints add a note of higher pitch, negative ones add a note of lower pitch.\n"
            "Example: 4,7 for a major third.\n\n"
            "Enter \"b\" to select a different effect.\n"
        )
        notes = input(">")
        if notes == "b":
            break
        notes = notes.split(",")
        processed = []
        for note in notes:
            try:
                note = int(note.strip())
            except ValueError:
                print("That is not a valid option.")
                continue
            processed.append(note)
        for track in tracks:
            for idx in range(len(track.events)-1, -1, -1):
                event = track.events[idx]
                if event.note is None:
                    continue
                for pitch in processed:
                    new_event = copy.copy(event)
                    new_event.timedelta = 0
                    new_event.note = max(0, min(127, event.note + pitch))
                    track.events.insert(idx + 1, new_event)
        print("Chorus added.")
        break


def delay(midi, tracks):
    """Adds a delay effect to all notes in a midi file."""
    while True:
        print(
            "Enter a series of integers seperated by commas denoting the number of 16th notes to delay by.\n"
            "Example: 1,2.\n\n"
            "Enter \"b\" to select a different effect.\n"
        )
        deltas = input(">")
        if deltas == "b":
            break
        deltas = deltas.split(",")
        processed = []
        for delta in deltas:
            try:
                delta = int(delta.strip())
            except ValueError:
                print("That is not a valid option.")
                continue
            if delta < 1:
                print("That is not a valid option.")
                continue
            quarters = delta / 4
            ticks = int(midi.per_quarter_note * quarters)
            processed.append(ticks)
        for track in tracks:
            for idx in range(len(track.events)-1, -1, -1):
                event = track.events[idx]
                if event.note is None:
                    continue
                for ticks in processed:
                    after = track.events[idx+1:]
                    # Sets `i` to equal the number of events after `idx` where the delay event should go.
                    # Sets `ticks` to equal the number of ticks after the last event.
                    for i, aftertrack in enumerate(after, 1):
                        if aftertrack.timedelta > ticks:
                            break
                        ticks -= aftertrack.timedelta
                    else:
                        i += 1
                    new_event = copy.copy(event)
                    new_event.timedelta = ticks
                    # Fixes the timedelta for the event after the event we are adding.
                    if len(track.events) > idx + i:
                        track.events[idx + i].timedelta -= ticks
                    track.events.insert(idx + i, new_event)
        print("Delay added.")
        break


# Main code loop
if __name__ == "__main__":
    print(
        "----=MIDI editor=----\n"
        "By Michael Oliveira\n"
        "MU 2300 Final Project\n"
    )
    # Select a file
    while True:
        fp = input("Enter a filepath to a MIDI file: ")
        if not fp.endswith(".mid"):
            print("Your filepath must point to a valid MIDI file. These files have the extension .mid.")
            continue
        try:
            with open(fp, "rb") as f:
                midi = MidiFile(f)
        except FileNotFoundError:
            print("Your filepath must point to a valid MIDI file. No file was found at that path.")
            continue
        except MIDIError as e:
            print(f"That MIDI file is not supported. {e}")
            continue
        # Select a track
        while True:
            print("What track do you want to modify?")
            for idx, track in enumerate(midi.tracks, 1):
                print(f"{idx}: Track {idx}")
            if len(midi.tracks) != 1:
                print("a: All tracks")
            print("b: Go back, and select a different file")
            print("s: Save your changes to a new file\n")
            track = input(">")
            if track == "a":
                track = "all"
            elif track == "b":
                break
            elif track == "s":
                result = midi.to_file()
                with open(f"output-{int(time.time())}.mid", "wb") as f:
                    f.write(result)
                print("File saved.")
                continue
            else:
                try:
                    track = int(track)
                except ValueError:
                    print("That is not a valid option.")
                    continue
                if track > len(midi.tracks) or track < 1:
                    print("That is not a valid option.")
                    continue
                track -= 1
            # Apply changes to that track
            while True:
                pretty_track = "all tracks" if track == "all" else f"track {track}"
                tracks = midi.tracks if track == "all" else [midi.tracks[track]]
                print(
                    f"Select an effect to apply to {pretty_track}.\n"
                    "1: Modify pitch.\n"
                    "2: Modify velocity.\n"
                    "3: Add choruses.\n"
                    "4: Add delays.\n"
                    "b: Go back, and select a different track.\n"
                    "s: Save your changes to a new file\n"
                )
                option = input(">")
                if option == "1":
                    pitch(midi, tracks)
                elif option == "2":
                    velocity(midi, tracks)
                elif option == "3":
                    chorus(midi, tracks)
                elif option == "4":
                    delay(midi, tracks)
                elif option == "b":
                    break
                elif option == "s":
                    result = midi.to_file()
                    with open(f"output-{int(time.time())}.mid", "wb") as f:
                        f.write(result)
                    print("File saved.")
                    continue
                elif option == "p":
                    print(midi)
                    continue
                else:
                    print("That is not a valid option.")
                    continue
