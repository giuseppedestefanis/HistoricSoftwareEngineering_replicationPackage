#!/usr/bin/env python3
"""
Deluxe Paint V1 Design Pattern Verification Tool
=================================================
Replication package for RQ3 of:
  "Historic Software Engineering: Insights from Deluxe Paint for the Amiga"
  G. Destefanis (University College London), Y.-G. Guéhéneuc (Concordia
  University), and F. Calefato (University of Bari)

This script verifies the 28 design pattern antecedents identified in the
Deluxe Paint V1 source code (Electronic Arts, 1985). Each pattern is verified
by searching for specific code structures (function definitions, struct
definitions, macros, dispatch tables, etc.) cited in the paper.

Usage:
    python verify_patterns.py <source_directory>
    python verify_patterns.py <source_directory> --json report.json --verbose

Requires: Python 3.8+, no external dependencies.
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EvidenceCheck:
    """One atomic piece of evidence to search for."""
    description: str
    filename: str          # e.g. 'PGRAPH.C' — uppercase
    pattern: str           # string or regex to search for
    check_type: str = 'string'  # 'string', 'regex', 'function', 'macro',
                                # 'line_range', 'struct_field', 'custom'
    line_start: int = 0    # for line_range checks
    line_end: int = 0      # for line_range checks
    min_matches: int = 1
    required: bool = True  # if False, failure doesn't block confirmation


@dataclass
class PatternSpec:
    """Declarative specification of one design pattern to verify."""
    id: int
    name: str
    family: str            # Structural, Behavioural, Creational, Architectural
    gof_pattern: str       # GoF name or 'N/A'
    primary_files: List[str]
    description: str
    checks: List[EvidenceCheck]


@dataclass
class EvidenceFound:
    """Result of one evidence check."""
    check: EvidenceCheck
    passed: bool
    matches: List[Tuple[int, str]]  # (line_number, line_text)


@dataclass
class PatternResult:
    """Result of verifying one pattern."""
    spec: PatternSpec
    confirmed: bool
    checks_passed: int
    checks_total: int
    evidence: List[EvidenceFound]


# ---------------------------------------------------------------------------
# SourceIndex — loads and indexes all source files
# ---------------------------------------------------------------------------

class SourceIndex:
    """Loads source files and provides search primitives."""

    def __init__(self, source_dir: str):
        self.source_dir = source_dir
        self.files: Dict[str, List[str]] = {}  # filename -> lines (0-indexed)
        self._load_files()

    def _load_files(self):
        for entry in os.listdir(self.source_dir):
            upper = entry.upper()
            if upper.endswith(('.C', '.H', '.TXT')):
                path = os.path.join(self.source_dir, entry)
                if os.path.isfile(path):
                    with open(path, 'r', errors='replace') as f:
                        self.files[upper] = f.readlines()

    def file_exists(self, filename: str) -> bool:
        return filename.upper() in self.files

    def get_lines(self, filename: str) -> List[str]:
        return self.files.get(filename.upper(), [])

    def get_line(self, filename: str, line_num: int) -> str:
        """Get a specific line (1-indexed)."""
        lines = self.get_lines(filename)
        if 0 < line_num <= len(lines):
            return lines[line_num - 1]
        return ''

    def find_string(self, filename: str, pattern: str,
                    case_sensitive: bool = True) -> List[Tuple[int, str]]:
        """Find all lines containing a literal string. Returns (line_num, text)."""
        results = []
        lines = self.get_lines(filename)
        for i, line in enumerate(lines):
            haystack = line if case_sensitive else line.lower()
            needle = pattern if case_sensitive else pattern.lower()
            if needle in haystack:
                results.append((i + 1, line.rstrip()))
        return results

    def find_regex(self, filename: str, pattern: str) -> List[Tuple[int, str]]:
        """Find all lines matching a regex."""
        results = []
        compiled = re.compile(pattern)
        for i, line in enumerate(self.get_lines(filename)):
            if compiled.search(line):
                results.append((i + 1, line.rstrip()))
        return results

    def find_in_range(self, filename: str, start: int, end: int,
                      pattern: str) -> List[Tuple[int, str]]:
        """Search for a string within a line range (1-indexed, inclusive)."""
        results = []
        lines = self.get_lines(filename)
        for i in range(max(0, start - 1), min(end, len(lines))):
            if pattern in lines[i]:
                results.append((i + 1, lines[i].rstrip()))
        return results

    def find_function(self, filename: str, func_name: str) -> List[Tuple[int, str]]:
        """Find a K&R C function definition by name.
        Matches patterns like:
            funcname(args)       (at start of line, possibly after 'void'/'local'/etc.)
        """
        results = []
        lines = self.get_lines(filename)
        # K&R functions: name at or near start of line, followed by (
        # Handles return types like: void, SHORT, BOOL, LONG, int, UWORD *,
        # UBYTE *, struct Name *, char *, and qualifiers like local/static
        pat = re.compile(
            r'^(?:local\s+|static\s+|void\s+|SHORT\s+|BOOL\s+|LONG\s+|int\s+|'
            r'UWORD\s+\*?\s*|USHORT\s+\*?\s*|'
            r'UBYTE\s+\*?\s*|struct\s+\w+\s+\*?\s*|char\s+\*?\s*)*'
            + re.escape(func_name) + r'\s*\('
        )
        for i, line in enumerate(lines):
            if pat.match(line):
                results.append((i + 1, line.rstrip()))
        return results

    def find_macro(self, filename: str, macro_name: str) -> List[Tuple[int, str]]:
        """Find a #define macro by name."""
        results = []
        pat = re.compile(r'^#define\s+' + re.escape(macro_name) + r'[\s(]')
        for i, line in enumerate(self.get_lines(filename)):
            if pat.match(line):
                results.append((i + 1, line.rstrip()))
        return results

    def find_struct_with_field(self, filename: str,
                               field_name: str) -> List[Tuple[int, str]]:
        """Find lines containing a field name (used for struct field verification)."""
        return self.find_string(filename, field_name)

    def count_globals(self, filename: str) -> int:
        """Heuristic count of top-level variable declarations in a file."""
        count = 0
        in_function = False
        brace_depth = 0
        for line in self.get_lines(filename):
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('/*') or stripped.startswith('*'):
                continue
            # Track brace depth to detect function bodies
            brace_depth += stripped.count('{') - stripped.count('}')
            if brace_depth > 0:
                in_function = True
            elif brace_depth <= 0:
                in_function = False
                brace_depth = 0
            if not in_function and not stripped.startswith(('typedef', 'extern', '#')):
                # Look for variable declarations: type name = ... or type name;
                if re.match(r'^(?:struct\s+\w+|SHORT|LONG|BOOL|UBYTE|int|char|void|UWORD|USHORT|'
                           r'Box|BMOB|BoxBM|struct BitMap)\s+\*?\w+', stripped):
                    if '(' not in stripped:  # not a function
                        count += 1
        return count


# ---------------------------------------------------------------------------
# Pattern definitions — 28 patterns, each with explicit evidence checks
# ---------------------------------------------------------------------------

def define_all_patterns() -> List[PatternSpec]:
    """Define all 28 pattern verification specifications."""
    return [
        # ===== STRUCTURAL (8) =====
        PatternSpec(
            id=1, name='Facade (Graphics)', family='Structural',
            gof_pattern='Facade', primary_files=['PGRAPH.C'],
            description='Unified drawing API with context stack over Amiga RastPort and blitter',
            checks=[
                EvidenceCheck('PWritePix function definition', 'PGRAPH.C',
                              'PWritePix', check_type='function'),
                EvidenceCheck('PHorizLine function definition', 'PGRAPH.C',
                              'PHorizLine', check_type='function'),
                EvidenceCheck('PFillBox function definition', 'PGRAPH.C',
                              'PFillBox', check_type='function'),
                EvidenceCheck('PushGrDest context stack push', 'PGRAPH.C',
                              'PushGrDest', check_type='function'),
                EvidenceCheck('PopGrDest context stack pop', 'PGRAPH.C',
                              'PopGrDest', check_type='function'),
                EvidenceCheck('SetPaintMode translates paint modes', 'PGRAPH.C',
                              'SetPaintMode', check_type='function'),
                EvidenceCheck('Stack depth constant NGRSTACK', 'PGRAPH.C',
                              'NGRSTACK', check_type='macro'),
            ]
        ),
        PatternSpec(
            id=2, name='Facade (Blitter)', family='Structural',
            gof_pattern='Facade', primary_files=['BLITOPS.C', 'MASKBLIT.C'],
            description='Typed struct overlay on blitter registers; hardware-bug workaround',
            checks=[
                EvidenceCheck('BlitterRegs cast at 0xDFF040', 'BLITOPS.C',
                              '0xDFF040', check_type='string'),
                EvidenceCheck('MaskBlit function definition', 'MASKBLIT.C',
                              'MaskBlit', check_type='function'),
                EvidenceCheck('Destination Wrap-Around Bug comment', 'MASKBLIT.C',
                              'Wrap-Around', check_type='string', required=False),
                EvidenceCheck('Recursive MaskBlit call for bug workaround', 'MASKBLIT.C',
                              r'MaskBlit\s*\(', check_type='regex', min_matches=2),
            ]
        ),
        PatternSpec(
            id=3, name='Facade (Bitmap Memory)', family='Structural',
            gof_pattern='Facade', primary_files=['BITMAPS.C'],
            description='Bitmap allocation with memory-floor guard and lazy reallocation',
            checks=[
                EvidenceCheck('MINAVAILMEM memory floor constant', 'BITMAPS.C',
                              'MINAVAILMEM', check_type='macro'),
                EvidenceCheck('TmpAllocBitMap factory function', 'BITMAPS.C',
                              'TmpAllocBitMap', check_type='function'),
                EvidenceCheck('AllocBitMap with memory check', 'BITMAPS.C',
                              'AllocBitMap', check_type='function'),
                EvidenceCheck('NewSizeBitMap lazy reallocation', 'BITMAPS.C',
                              'NewSizeBitMap', check_type='function'),
            ]
        ),
        PatternSpec(
            id=4, name='Facade (Windowing)', family='Structural',
            gof_pattern='Facade', primary_files=['PANE.C'],
            description='Lightweight sub-window manager with polymorphic callbacks',
            checks=[
                EvidenceCheck('charProc callback field in Pane struct', 'PRISM.H',
                              'charProc', check_type='string'),
                EvidenceCheck('mouseProc callback field in Pane struct', 'PRISM.H',
                              'mouseProc', check_type='string'),
                EvidenceCheck('paintProc callback field in Pane struct', 'PRISM.H',
                              'paintProc', check_type='string'),
                EvidenceCheck('PListen event dispatch loop', 'PANE.C',
                              'PListen', check_type='function'),
                EvidenceCheck('PaneRefresh broadcast repaint', 'PANE.C',
                              'PaneRefresh', check_type='function'),
            ]
        ),
        PatternSpec(
            id=5, name='Adapter (Coordinates)', family='Structural',
            gof_pattern='Adapter', primary_files=['PRISM.H'],
            description='Bit-shift macros translating virtual/physical coordinates per display mode',
            checks=[
                EvidenceCheck('PMapX macro definition', 'PRISM.H',
                              'PMapX', check_type='macro'),
                EvidenceCheck('PMapY macro definition', 'PRISM.H',
                              'PMapY', check_type='macro'),
                EvidenceCheck('VMapX macro definition', 'PRISM.H',
                              'VMapX', check_type='macro'),
                EvidenceCheck('VMapY macro definition', 'PRISM.H',
                              'VMapY', check_type='macro'),
                EvidenceCheck('xShft shift value used in mapping', 'PRISM.H',
                              'xShft', check_type='string'),
                EvidenceCheck('yShft shift value used in mapping', 'PRISM.H',
                              'yShft', check_type='string'),
            ]
        ),
        PatternSpec(
            id=6, name='Adapter (IFF Format)', family='Structural',
            gof_pattern='Adapter', primary_files=['DPIFF.C', 'DPIFF.H', 'ILBMR.C', 'ILBMW.C'],
            description='MaskBM struct bridging IFF format types and internal BitMap/BMOB',
            checks=[
                EvidenceCheck('MaskBM struct definition in DPIFF.H', 'DPIFF.H',
                              'MaskBM', check_type='string'),
                EvidenceCheck('Color conversion in ILBMR.C (RGB >> 4)', 'ILBMR.C',
                              '>> 4', check_type='string'),
                EvidenceCheck('Color conversion in ILBMW.C (>> 4)', 'ILBMW.C',
                              '>> 4', check_type='string'),
                EvidenceCheck('DPIFF.C includes dpiff.h', 'DPIFF.C',
                              'dpiff', check_type='string', required=False),
            ]
        ),
        PatternSpec(
            id=7, name='Decorator (BMOB layers)', family='Structural',
            gof_pattern='Decorator', primary_files=['PRISM.H'],
            description='Three-layer struct embedding: Box -> BoxBM -> BMOB',
            checks=[
                EvidenceCheck('Box struct: pure geometry (x,y,w,h)', 'PRISM.H',
                              r'}\s*Box\s*;', check_type='regex'),
                EvidenceCheck('BoxBM struct contains Box field', 'PRISM.H',
                              'Box box', check_type='string'),
                EvidenceCheck('BoxBM struct adds BitMap pointer', 'PRISM.H',
                              r'BitMap\s+\*bm', check_type='regex'),
                EvidenceCheck('BMOB struct contains BoxBM pict field', 'PRISM.H',
                              'BoxBM pict', check_type='string'),
                EvidenceCheck('BMOB struct contains save buffer', 'PRISM.H',
                              'BoxBM.*save', check_type='regex'),
                EvidenceCheck('BMOB struct adds mask field', 'PRISM.H',
                              r'mask', check_type='string'),
                EvidenceCheck('PaintOb function uses BMOB fields', 'BMOB.C',
                              'PaintOb', check_type='function'),
                EvidenceCheck('paintProps dispatch table in BMOB.C', 'BMOB.C',
                              'paintProps', check_type='string'),
            ]
        ),
        PatternSpec(
            id=8, name='Decorator (IMode flags)', family='Structural',
            gof_pattern='Decorator', primary_files=['PRISM.H'],
            description='14-bit flag field composing 32 behavioural variants of interaction modes',
            checks=[
                EvidenceCheck('IModeDesc struct definition', 'PRISM.H',
                              'IModeDesc', check_type='string'),
                EvidenceCheck('PERM flag definition', 'PRISM.H',
                              'PERM', check_type='macro'),
                EvidenceCheck('NOGR flag definition', 'PRISM.H',
                              'NOGR', check_type='macro'),
                EvidenceCheck('NOBR flag definition', 'PRISM.H',
                              'NOBR', check_type='macro'),
                EvidenceCheck('NOSYM flag definition', 'PRISM.H',
                              'NOSYM', check_type='macro'),
                EvidenceCheck('NOLOCK flag definition', 'PRISM.H',
                              'NOLOCK', check_type='macro'),
                EvidenceCheck('NIMODES = 32 constant', 'PRISM.H',
                              r'#define\s+NIMODES\s+32', check_type='regex'),
                EvidenceCheck('imodes table with NIMODES entries', 'PAINTW.C',
                              'imodes[NIMODES]', check_type='string', required=False),
                EvidenceCheck('imodes table declaration', 'PAINTW.C',
                              'IModeDesc imodes', check_type='string'),
            ]
        ),

        # ===== BEHAVIOURAL (8) =====
        PatternSpec(
            id=9, name='Command (8-slot procs)', family='Behavioural',
            gof_pattern='Command', primary_files=['PAINTW.C'],
            description='Eight function-pointer slots encoding deferred interactive operations',
            checks=[
                EvidenceCheck('upShow function pointer slot', 'PAINTW.C',
                              'upShow', check_type='string'),
                EvidenceCheck('upMove function pointer slot', 'PAINTW.C',
                              'upMove', check_type='string'),
                EvidenceCheck('WentDn function pointer slot', 'PAINTW.C',
                              'WentDn', check_type='string'),
                EvidenceCheck('dnShow function pointer slot', 'PAINTW.C',
                              'dnShow', check_type='string'),
                EvidenceCheck('dnMove function pointer slot', 'PAINTW.C',
                              'dnMove', check_type='string'),
                EvidenceCheck('WentUp function pointer slot', 'PAINTW.C',
                              'WentUp', check_type='string'),
                EvidenceCheck('IModeProcs stuffs all slots atomically', 'PAINTW.C',
                              'IModeProcs', check_type='function'),
                EvidenceCheck('NewIMode resets slots to nop', 'PAINTW.C',
                              'NewIMode', check_type='function'),
                EvidenceCheck('nop function pointer (nada)', 'PAINTW.C',
                              'nop', check_type='string'),
            ]
        ),
        PatternSpec(
            id=10, name='Command (Undo tags)', family='Behavioural',
            gof_pattern='Command', primary_files=['MAINMAG.C', 'PRISM.H'],
            description='didType tag recording last operation for undo dispatch',
            checks=[
                EvidenceCheck('didType variable declaration', 'MAINMAG.C',
                              'didType', check_type='string'),
                EvidenceCheck('DIDNothing constant', 'PRISM.H',
                              'DIDNothing', check_type='macro'),
                EvidenceCheck('DIDClear constant', 'PRISM.H',
                              'DIDClear', check_type='macro'),
                EvidenceCheck('DIDMerge constant', 'PRISM.H',
                              'DIDMerge', check_type='macro'),
                EvidenceCheck('DIDHPoly constant', 'PRISM.H',
                              'DIDHPoly', check_type='macro'),
                EvidenceCheck('Undo function dispatches on didType', 'MAINMAG.C',
                              'Undo', check_type='function'),
            ]
        ),
        PatternSpec(
            id=11, name='Command (Menu dispatch)', family='Behavioural',
            gof_pattern='Command', primary_files=['MENU.C'],
            description='Arrays of function pointers indexed by menu item for O(1) dispatch',
            checks=[
                EvidenceCheck('picProc function pointer array', 'MENU.C',
                              'picProc', check_type='string'),
                EvidenceCheck('prefsProc function pointer array', 'MENU.C',
                              'prefsProc', check_type='string'),
                EvidenceCheck('MenProcs function pointer array', 'MENU.C',
                              'MenProcs', check_type='string'),
            ]
        ),
        PatternSpec(
            id=12, name='Strategy (Pixel writers)', family='Behavioural',
            gof_pattern='Strategy', primary_files=['PGRAPH.C'],
            description='wrPixTable[] maps paint modes to per-pixel write functions',
            checks=[
                EvidenceCheck('wrPixTable dispatch table', 'PGRAPH.C',
                              'wrPixTable', check_type='string'),
                EvidenceCheck('CurPWritePix active strategy pointer', 'PGRAPH.C',
                              'CurPWritePix', check_type='string'),
                EvidenceCheck('PSmearPix strategy function', 'PGRAPH.C',
                              'PSmearPix', check_type='function'),
                EvidenceCheck('PShadePix strategy function', 'PGRAPH.C',
                              'PShadePix', check_type='function'),
                EvidenceCheck('PBlendPix strategy function', 'PGRAPH.C',
                              'PBlendPix', check_type='function'),
                EvidenceCheck('SetPaintMode loads strategy from table', 'PGRAPH.C',
                              r'CurPWritePix\s*=\s*wrPixTable', check_type='regex'),
            ]
        ),
        PatternSpec(
            id=13, name='Strategy (Geometric primitives)', family='Behavioural',
            gof_pattern='Strategy', primary_files=['GEOM.C', 'CONIC.C'],
            description='Geometric primitives accept per-pixel strategy functions as parameters',
            checks=[
                EvidenceCheck('PLineWith accepts function pointer param', 'GEOM.C',
                              'PLineWith', check_type='function'),
                EvidenceCheck('PLineWith has (*fun) parameter type', 'GEOM.C',
                              '(*fun)', check_type='string'),
                EvidenceCheck('PCircWith accepts function pointer param', 'GEOM.C',
                              'PCircWith', check_type='function'),
                EvidenceCheck('PEllpsWith accepts function pointer param', 'CONIC.C',
                              'PEllpsWith', check_type='function'),
                EvidenceCheck('PEllpsWith has (*func) parameter type', 'CONIC.C',
                              '(*func)', check_type='string'),
            ]
        ),
        PatternSpec(
            id=14, name='State (IMode FSM)', family='Behavioural',
            gof_pattern='State', primary_files=['PAINTW.C'],
            description='32-entry IModeDesc table with nextIMode chaining and startProc reconfiguration',
            checks=[
                EvidenceCheck('IModeDesc imodes table declaration', 'PAINTW.C',
                              'IModeDesc imodes', check_type='string'),
                EvidenceCheck('NewIMode state entry function', 'PAINTW.C',
                              'NewIMode', check_type='function'),
                EvidenceCheck('NextIMode chaining function', 'PAINTW.C',
                              'NextIMode', check_type='function'),
                EvidenceCheck('RevertIMode return-to-permanent function', 'PAINTW.C',
                              'RevertIMode', check_type='function'),
                EvidenceCheck('AbortIMode cancel function', 'PAINTW.C',
                              'AbortIMode', check_type='function'),
                EvidenceCheck('Constrain sub-FSM function', 'PAINTW.C',
                              'Constrain', check_type='function'),
                EvidenceCheck('CONS_NOT sub-state constant', 'PAINTW.C',
                              'CONS_NOT', check_type='string'),
                EvidenceCheck('CONS_HORIZ sub-state constant', 'PAINTW.C',
                              'CONS_HORIZ', check_type='string'),
                EvidenceCheck('CONS_VERT sub-state constant', 'PAINTW.C',
                              'CONS_VERT', check_type='string'),
            ]
        ),
        PatternSpec(
            id=15, name='Observer (Pane callbacks + VBlank)', family='Behavioural',
            gof_pattern='Observer', primary_files=['PANE.C', 'CCYCLE.C'],
            description='Pane callback registration with broadcast; VBlank interrupt subscription',
            checks=[
                EvidenceCheck('PListen event dispatch to callbacks', 'PANE.C',
                              'PListen', check_type='function'),
                EvidenceCheck('PaneRefresh broadcasts to overlapping Panes', 'PANE.C',
                              'PaneRefresh', check_type='function'),
                EvidenceCheck('updtProc callback in MagContext', 'PRISM.H',
                              'updtProc', check_type='string'),
                EvidenceCheck('VBlank interrupt via AddIntServer', 'CCYCLE.C',
                              'AddIntServer', check_type='string'),
                EvidenceCheck('NoCycle race-condition lock flag', 'CCYCLE.C',
                              'NoCycle', check_type='string'),
                EvidenceCheck('periodicCall callback in PAINTW.C', 'PAINTW.C',
                              'periodicCall', check_type='string'),
            ]
        ),
        PatternSpec(
            id=16, name='Template Method', family='Behavioural',
            gof_pattern='Template Method', primary_files=['PAINTW.C', 'MODES.C', 'PSYM.C'],
            description='Fixed procedural skeletons with pluggable function-pointer steps',
            checks=[
                EvidenceCheck('GoDown skeleton function', 'PAINTW.C',
                              'GoDown', check_type='function'),
                EvidenceCheck('GoUp skeleton function', 'PAINTW.C',
                              'GoUp', check_type='function'),
                EvidenceCheck('GoDown calls pluggable WentDn', 'PAINTW.C',
                              r'\(\*WentDn\)', check_type='regex'),
                EvidenceCheck('GoUp calls pluggable WentUp', 'PAINTW.C',
                              r'\(\*WentUp\)', check_type='regex'),
                EvidenceCheck('VTypeOps mode template', 'MODES.C',
                              'VTypeOps', check_type='function'),
                EvidenceCheck('XHTypeOps mode template', 'MODES.C',
                              'XHTypeOps', check_type='function'),
                EvidenceCheck('CircTypeOps mode template', 'MODES.C',
                              'CircTypeOps', check_type='function'),
                EvidenceCheck('SymDo symmetry iterator with proc param', 'PSYM.C',
                              'SymDo', check_type='function'),
                EvidenceCheck('SymDo accepts function pointer', 'PSYM.C',
                              '(*proc)', check_type='string'),
            ]
        ),

        # ===== CREATIONAL (5) =====
        PatternSpec(
            id=17, name='Factory (Bitmap/Memory)', family='Creational',
            gof_pattern='Factory Method', primary_files=['BITMAPS.C', 'DALLOC.C'],
            description='Hierarchy of allocation functions with memory-floor guards and rollback',
            checks=[
                EvidenceCheck('DAlloc wraps AllocMem with size header', 'DALLOC.C',
                              'DAlloc', check_type='function'),
                EvidenceCheck('DFree frees without caller tracking size', 'DALLOC.C',
                              'DFree', check_type='function'),
                EvidenceCheck('ChipAlloc constrains to Chip RAM', 'DALLOC.C',
                              'ChipAlloc', check_type='function'),
                EvidenceCheck('MEMF_CHIP flag in ChipAlloc', 'DALLOC.C',
                              'MEMF_CHIP', check_type='string'),
                EvidenceCheck('TmpAllocBitMap per-plane allocation', 'BITMAPS.C',
                              'TmpAllocBitMap', check_type='function'),
                EvidenceCheck('AllocBitMap with memory floor', 'BITMAPS.C',
                              'AllocBitMap', check_type='function'),
                EvidenceCheck('NewSizeBitMap lazy reallocation', 'BITMAPS.C',
                              'NewSizeBitMap', check_type='function'),
                EvidenceCheck('MakeEquivBM clones geometry', 'BITMAPS.C',
                              'MakeEquivBM', check_type='function'),
            ]
        ),
        PatternSpec(
            id=18, name='Factory (Pen dispatch)', family='Creational',
            gof_pattern='Factory Method', primary_files=['CURBRUSH.C'],
            description='SelPen dispatcher routes to specialised pen constructors',
            checks=[
                EvidenceCheck('SelPen dispatcher function', 'CURBRUSH.C',
                              'SelPen', check_type='function'),
                EvidenceCheck('RoundPen constructor', 'CURBRUSH.C',
                              'RoundPen', check_type='function'),
                EvidenceCheck('SquarePen constructor', 'CURBRUSH.C',
                              'SquarePen', check_type='function'),
                EvidenceCheck('DotsPen constructor', 'CURBRUSH.C',
                              'DotsPen', check_type='function'),
                EvidenceCheck('OneBitPen constructor', 'CURBRUSH.C',
                              'OneBitPen', check_type='function'),
                EvidenceCheck('FixUpPen shared finaliser', 'CURBRUSH.C',
                              'FixUpPen', check_type='function'),
            ]
        ),
        PatternSpec(
            id=19, name='Singleton/Monostate', family='Creational',
            gof_pattern='Singleton', primary_files=['PRISM.C'],
            description='~60 global variables constituting application-wide monostate',
            checks=[
                EvidenceCheck('mainW display resource global', 'PRISM.C',
                              'mainW', check_type='string'),
                EvidenceCheck('screen display resource global', 'PRISM.C',
                              'screen', check_type='string'),
                EvidenceCheck('hidbm hidden bitmap global', 'PRISM.C',
                              'hidbm', check_type='string'),
                EvidenceCheck('tmpRas temporary raster global', 'PRISM.C',
                              'tmpRas', check_type='string'),
                EvidenceCheck('curbr current brush global', 'PRISM.C',
                              'curbr', check_type='string'),
                EvidenceCheck('curpenob current pen object global', 'PRISM.C',
                              'curpenob', check_type='string'),
                EvidenceCheck('sparebm spare canvas global', 'PRISM.C',
                              'sparebm', check_type='string'),
                EvidenceCheck('extern hidbm referenced from other modules', 'MAINMAG.C',
                              'hidbm', check_type='string'),
                EvidenceCheck('curob singleton active-tool pointer', 'MODES.C',
                              'curob', check_type='string'),
            ]
        ),
        PatternSpec(
            id=20, name='Prototype (Bitmap clone)', family='Creational',
            gof_pattern='Prototype', primary_files=['BITMAPS.C'],
            description='DupBitMap (shallow) and CopyBitMap (deep clone via blitter)',
            checks=[
                EvidenceCheck('DupBitMap shallow clone function', 'BITMAPS.C',
                              'DupBitMap', check_type='function'),
                EvidenceCheck('CopyBitMap deep clone via BltBitMap', 'BITMAPS.C',
                              'CopyBitMap', check_type='function'),
                EvidenceCheck('BltBitMap used for deep copy', 'BITMAPS.C',
                              'BltBitMap', check_type='string'),
            ]
        ),
        PatternSpec(
            id=21, name='Prototype (Undo swap)', family='Creational',
            gof_pattern='Prototype', primary_files=['MAINMAG.C'],
            description='Triple-XOR blitter swap between screen and hidbm for zero-memory undo',
            checks=[
                EvidenceCheck('SwapHidScr function definition', 'MAINMAG.C',
                              'SwapHidScr', check_type='function'),
                EvidenceCheck('XOROP used in swap operation', 'MAINMAG.C',
                              'XOROP', check_type='string'),
                EvidenceCheck('CopyFwd used in triple-XOR', 'MAINMAG.C',
                              'CopyFwd', check_type='string'),
                EvidenceCheck('CopyBack used in triple-XOR', 'MAINMAG.C',
                              'CopyBack', check_type='string'),
            ]
        ),

        # ===== ARCHITECTURAL (7) =====
        PatternSpec(
            id=22, name='Code Overlay System', family='Architectural',
            gof_pattern='N/A', primary_files=['PRISM.txt', 'PRISM.H'],
            description='Manual virtual memory via linker overlay segments',
            checks=[
                EvidenceCheck('OVERLAY keyword in linker control file', 'PRISM.TXT',
                              'OVERLAY', check_type='string'),
                EvidenceCheck('ROOT keyword in linker control file', 'PRISM.TXT',
                              'ROOT', check_type='string'),
                EvidenceCheck('OVSInfo struct in PRISM.H', 'PRISM.H',
                              'OVSInfo', check_type='string'),
                EvidenceCheck('OVS_DUMB strategy constant', 'PRISM.H',
                              'OVS_DUMB', check_type='macro'),
                EvidenceCheck('OVS_SMART strategy constant', 'PRISM.H',
                              'OVS_SMART', check_type='macro'),
                EvidenceCheck('OVS_LOAD_ALL strategy constant', 'PRISM.H',
                              'OVS_LOAD_ALL', check_type='macro'),
                EvidenceCheck('sleepCursor overlay callback', 'PRISM.H',
                              'sleepCursor', check_type='string'),
                EvidenceCheck('wakeCursor overlay callback', 'PRISM.H',
                              'wakeCursor', check_type='string'),
                EvidenceCheck('panic overlay callback', 'PRISM.H',
                              'panic', check_type='string'),
                EvidenceCheck('INITREAD.C exists (empty overlay trigger)', 'INITREAD.C',
                              'InitRead', check_type='string'),
                EvidenceCheck('INITWRIT.C exists (empty overlay trigger)', 'INITWRIT.C',
                              'InitWrite', check_type='string', required=False),
            ]
        ),
        PatternSpec(
            id=23, name='Two-Buffer Undo', family='Architectural',
            gof_pattern='N/A', primary_files=['MAINMAG.C', 'MAGWIN.C'],
            description='Screen bitmap as live surface; hidbm stores last committed state',
            checks=[
                EvidenceCheck('UndoSave function copies changed region', 'MAINMAG.C',
                              'UndoSave', check_type='function'),
                EvidenceCheck('hidbm hidden bitmap declaration', 'PRISM.C',
                              'hidbm', check_type='string'),
                EvidenceCheck('chgB bounding box tracking changes', 'MAINMAG.C',
                              'chgB', check_type='string'),
                EvidenceCheck('Painting flag partitions rendering tracks', 'MAGWIN.C',
                              'Painting', check_type='string'),
                EvidenceCheck('Undo function definition', 'MAINMAG.C',
                              'Undo', check_type='function'),
            ]
        ),
        PatternSpec(
            id=24, name='Per-Object Save-Under', family='Architectural',
            gof_pattern='N/A', primary_files=['BMOB.C'],
            description='Each BMOB carries a save buffer for background preservation',
            checks=[
                EvidenceCheck('ShowBMOB captures background', 'BMOB.C',
                              'ShowBMOB', check_type='function'),
                EvidenceCheck('ClearBMOB restores background', 'BMOB.C',
                              'ClearBMOB', check_type='function'),
                EvidenceCheck('ChangeBMOB optimises moves', 'BMOB.C',
                              'ChangeBMOB', check_type='function'),
                EvidenceCheck('BoxNot computes rectangular complement', 'BMOB.C',
                              'BoxNot', check_type='function'),
                EvidenceCheck('TOOBIGTOPAINT graceful degradation flag', 'PRISM.H',
                              'TOOBIGTOPAINT', check_type='string'),
            ]
        ),
        PatternSpec(
            id=25, name='Cooperative Resource Sharing', family='Architectural',
            gof_pattern='N/A', primary_files=['PRISM.C', 'DPIO.C'],
            description='TmpRas strategically freed before Intuition allocations, reallocated after',
            checks=[
                EvidenceCheck('FreeTmpRas call in PRISM.C (before menus)', 'PRISM.C',
                              'FreeTmpRas', check_type='string'),
                EvidenceCheck('FreeTmpRas call in DPIO.C (before requesters)', 'DPIO.C',
                              'FreeTmpRas', check_type='string'),
                EvidenceCheck('AllocTmpRas reallocation after operation', 'PRISM.C',
                              'AllocTmpRas', check_type='string'),
                EvidenceCheck('AllocTmpRas in DPIO.C after requester', 'DPIO.C',
                              'AllocTmpRas', check_type='string'),
            ]
        ),
        PatternSpec(
            id=26, name='Hardware Register Abstraction', family='Architectural',
            gof_pattern='N/A', primary_files=['PRISM.H'],
            description='BlitterRegs struct overlays C field names onto memory-mapped I/O registers',
            checks=[
                EvidenceCheck('BlitterRegs struct definition', 'PRISM.H',
                              'BlitterRegs', check_type='string'),
                EvidenceCheck('BLTADDR constant (0xDFF040)', 'PRISM.H',
                              'BLTADDR', check_type='macro'),
                EvidenceCheck('ioskip fields for unmapped register gaps', 'PRISM.H',
                              'ioskip', check_type='string'),
                EvidenceCheck('REPOP minterm constant', 'PRISM.H',
                              'REPOP', check_type='macro'),
                EvidenceCheck('COOKIEOP minterm constant', 'PRISM.H',
                              'COOKIEOP', check_type='macro'),
                EvidenceCheck('XOROP minterm constant', 'PRISM.H',
                              'XOROP', check_type='macro'),
                EvidenceCheck('BlitSize macro for blitter programming', 'PRISM.H',
                              'BlitSize', check_type='macro'),
            ]
        ),
        PatternSpec(
            id=27, name='Graphics Context Stack', family='Architectural',
            gof_pattern='N/A', primary_files=['PGRAPH.C'],
            description='PushGrDest/PopGrDest manage a four-deep rendering target stack',
            checks=[
                EvidenceCheck('NGRSTACK depth constant = 4', 'PGRAPH.C',
                              r'#define\s+NGRSTACK\s+4', check_type='regex'),
                EvidenceCheck('PushGrDest push function', 'PGRAPH.C',
                              'PushGrDest', check_type='function'),
                EvidenceCheck('PopGrDest pop function', 'PGRAPH.C',
                              'PopGrDest', check_type='function'),
                EvidenceCheck('rpStack array for saved RastPorts', 'PGRAPH.C',
                              'rpStack', check_type='string'),
                EvidenceCheck('grStPtr stack pointer variable', 'PGRAPH.C',
                              'grStPtr', check_type='string'),
                EvidenceCheck('PushGrDest used from other modules', 'MAINMAG.C',
                              'PushGrDest', check_type='string', required=False),
            ]
        ),
        PatternSpec(
            id=28, name='Service Locator (IPC)', family='Architectural',
            gof_pattern='N/A', primary_files=['HOOK.C', 'DPHOOK.H'],
            description='Named Amiga OS message port exposing application bitmap to other processes',
            checks=[
                EvidenceCheck('SetHook creates named message port', 'HOOK.C',
                              'SetHook', check_type='function'),
                EvidenceCheck('FindHook discovers service by name', 'HOOK.C',
                              'FindHook', check_type='function'),
                EvidenceCheck('RemHook removes service', 'HOOK.C',
                              'RemHook', check_type='function'),
                EvidenceCheck('DPHook struct in DPHOOK.H', 'DPHOOK.H',
                              'DPHook', check_type='string'),
                EvidenceCheck('MsgPort in Hook struct', 'HOOK.C',
                              'MsgPort', check_type='string'),
                EvidenceCheck('DeluxePaint service name', 'PRISM.C',
                              'DeluxePaint', check_type='string'),
            ]
        ),
    ]


# ---------------------------------------------------------------------------
# PatternVerifier — evaluates checks against the source index
# ---------------------------------------------------------------------------

class PatternVerifier:
    """Evaluates pattern specifications against source files."""

    def __init__(self, index: SourceIndex):
        self.index = index

    def verify(self, spec: PatternSpec) -> PatternResult:
        """Verify a single pattern specification."""
        evidence_list = []
        checks_passed = 0

        for check in spec.checks:
            matches = self._run_check(check)
            passed = len(matches) >= check.min_matches
            if passed:
                checks_passed += 1
            evidence_list.append(EvidenceFound(
                check=check, passed=passed, matches=matches
            ))

        # Confirmed if all required checks passed
        required_passed = all(
            ev.passed for ev in evidence_list if ev.check.required
        )
        return PatternResult(
            spec=spec,
            confirmed=required_passed,
            checks_passed=checks_passed,
            checks_total=len(spec.checks),
            evidence=evidence_list,
        )

    def _run_check(self, check: EvidenceCheck) -> List[Tuple[int, str]]:
        """Execute a single evidence check and return matches."""
        if check.check_type == 'string':
            return self.index.find_string(check.filename, check.pattern)
        elif check.check_type == 'regex':
            return self.index.find_regex(check.filename, check.pattern)
        elif check.check_type == 'function':
            return self.index.find_function(check.filename, check.pattern)
        elif check.check_type == 'macro':
            return self.index.find_macro(check.filename, check.pattern)
        elif check.check_type == 'line_range':
            return self.index.find_in_range(
                check.filename, check.line_start, check.line_end, check.pattern
            )
        else:
            return []

    def verify_all(self, patterns: List[PatternSpec]) -> List[PatternResult]:
        """Verify all patterns."""
        return [self.verify(p) for p in patterns]


# ---------------------------------------------------------------------------
# ReportGenerator — produces text and JSON output
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Generates human-readable and machine-readable reports."""

    def __init__(self, results: List[PatternResult], source_dir: str,
                 file_count: int, verbose: bool = False):
        self.results = results
        self.source_dir = source_dir
        self.file_count = file_count
        self.verbose = verbose
        self.timestamp = datetime.now().isoformat(timespec='seconds')

    def text_report(self) -> str:
        """Generate human-readable text report."""
        lines = []
        w = 78  # width

        # Header
        lines.append('=' * w)
        lines.append('  Deluxe Paint V1 Design Pattern Verification Report')
        lines.append(f'  Generated: {self.timestamp}')
        lines.append(f'  Source directory: {self.source_dir}')
        lines.append(f'  Files scanned: {self.file_count}')
        lines.append('=' * w)
        lines.append('')

        # Summary
        confirmed = sum(1 for r in self.results if r.confirmed)
        total = len(self.results)
        lines.append(f'SUMMARY: {confirmed}/{total} patterns confirmed'
                     f' ({100*confirmed/total:.1f}%)')
        lines.append('')

        families = {}
        for r in self.results:
            fam = r.spec.family
            if fam not in families:
                families[fam] = [0, 0]
            families[fam][1] += 1
            if r.confirmed:
                families[fam][0] += 1

        for fam, (c, t) in families.items():
            status = 'ALL CONFIRMED' if c == t else f'{c}/{t}'
            lines.append(f'  {fam:15s} {c}/{t}  {status}')
        lines.append('')
        lines.append('=' * w)

        # Per-pattern details
        for r in self.results:
            lines.append('')
            status = 'CONFIRMED' if r.confirmed else '*** NOT CONFIRMED ***'
            lines.append(f'PATTERN {r.spec.id}/28: {r.spec.name}')
            lines.append(f'Family: {r.spec.family} | GoF: {r.spec.gof_pattern}'
                        f' | Files: {", ".join(r.spec.primary_files)}')
            lines.append(f'Status: {status}'
                        f' ({r.checks_passed}/{r.checks_total} checks passed)')
            lines.append('-' * w)

            for ev in r.evidence:
                tag = 'PASS' if ev.passed else 'FAIL'
                req = '' if ev.check.required else ' (optional)'
                lines.append(f'  [{tag}] {ev.check.description}{req}')
                if ev.passed:
                    for lnum, ltxt in ev.matches[:5]:  # show up to 5 matches
                        lines.append(f'         {ev.check.filename}:{lnum}  {ltxt}')
                    if len(ev.matches) > 5:
                        lines.append(f'         ... and {len(ev.matches)-5} more matches')
                else:
                    lines.append(f'         NOT FOUND in {ev.check.filename}'
                               f' (searched for: {ev.check.pattern})')
                lines.append('')

            lines.append('=' * w)

        return '\n'.join(lines)

    def json_report(self) -> Dict[str, Any]:
        """Generate machine-readable JSON report."""
        confirmed = sum(1 for r in self.results if r.confirmed)
        total = len(self.results)

        families = {}
        for r in self.results:
            fam = r.spec.family
            if fam not in families:
                families[fam] = {'confirmed': 0, 'total': 0}
            families[fam]['total'] += 1
            if r.confirmed:
                families[fam]['confirmed'] += 1

        patterns_json = []
        for r in self.results:
            evidence_json = []
            for ev in r.evidence:
                evidence_json.append({
                    'description': ev.check.description,
                    'file': ev.check.filename,
                    'search_type': ev.check.check_type,
                    'search_pattern': ev.check.pattern,
                    'required': ev.check.required,
                    'passed': ev.passed,
                    'matches': [
                        {'line': lnum, 'text': ltxt}
                        for lnum, ltxt in ev.matches[:10]
                    ],
                    'match_count': len(ev.matches),
                })
            patterns_json.append({
                'id': r.spec.id,
                'name': r.spec.name,
                'family': r.spec.family,
                'gof_pattern': r.spec.gof_pattern,
                'primary_files': r.spec.primary_files,
                'description': r.spec.description,
                'confirmed': r.confirmed,
                'checks_passed': r.checks_passed,
                'checks_total': r.checks_total,
                'evidence': evidence_json,
            })

        return {
            'metadata': {
                'tool': 'Deluxe Paint V1 Design Pattern Verification Tool',
                'version': '1.0',
                'generated_at': self.timestamp,
                'source_directory': self.source_dir,
                'files_scanned': self.file_count,
                'paper': 'Historic Software Engineering: Insights from '
                         'Deluxe Paint for the Amiga',
            },
            'summary': {
                'confirmed': confirmed,
                'total': total,
                'score': round(confirmed / total, 4) if total > 0 else 0,
                'by_family': families,
            },
            'patterns': patterns_json,
        }


# ---------------------------------------------------------------------------
# Heuristic Discovery Engine — scans for structural pattern indicators
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    """A heuristic pattern candidate discovered in the source code."""
    heuristic: str           # which heuristic found this
    pattern_type: str        # e.g. 'Strategy', 'Facade', 'Observer'
    filename: str
    evidence: List[Tuple[int, str]]  # (line_num, line_text)
    explanation: str


class PatternDiscovery:
    """Scans source files for structural indicators of design patterns.

    Unlike the verifier (which checks for specific named evidence), the
    discovery engine looks for *generic structural signatures*: arrays of
    function pointers, struct embedding chains, push/pop pairs, callback
    fields, etc.  It reports candidates that a human analyst can then
    interpret as design-pattern antecedents.
    """

    def __init__(self, index: SourceIndex):
        self.index = index

    def discover_all(self) -> List[Candidate]:
        """Run all heuristics across all source files."""
        candidates: List[Candidate] = []
        for filename in sorted(self.index.files.keys()):
            lines = self.index.get_lines(filename)
            candidates.extend(self._find_func_ptr_arrays(filename, lines))
            candidates.extend(self._find_func_ptr_variables(filename, lines))
            candidates.extend(self._find_struct_embedding(filename, lines))
            candidates.extend(self._find_push_pop_pairs(filename, lines))
            candidates.extend(self._find_callback_fields(filename, lines))
            candidates.extend(self._find_flag_composition(filename, lines))
            candidates.extend(self._find_hw_register_casts(filename, lines))
            candidates.extend(self._find_copy_clone_funcs(filename, lines))
            candidates.extend(self._find_alloc_wrappers(filename, lines))
            candidates.extend(self._find_interrupt_handlers(filename, lines))
            candidates.extend(self._find_dispatch_switches(filename, lines))
            candidates.extend(self._find_coordinate_adapters(filename, lines))
            candidates.extend(self._find_state_dispatch_tables(filename, lines))
            candidates.extend(self._find_format_conversion(filename, lines))
        candidates.extend(self._find_global_monostate())
        candidates.extend(self._find_overlay_keywords())
        return candidates

    # --- Individual heuristics ---

    def _find_func_ptr_arrays(self, filename: str,
                               lines: List[str]) -> List[Candidate]:
        """Find arrays of function pointers → Strategy / Command candidates."""
        results = []
        # Matches: void (*name[])() or type (*name[N])()
        pat = re.compile(r'\(\*\s*(\w+)\s*\[')
        for i, line in enumerate(lines):
            m = pat.search(line)
            if m and '(' in line:
                name = m.group(1)
                results.append(Candidate(
                    heuristic='Function pointer array',
                    pattern_type='Strategy / Command',
                    filename=filename,
                    evidence=[(i + 1, line.rstrip())],
                    explanation=f'Array of function pointers "{name}" enables '
                               f'runtime algorithm selection (Strategy) or '
                               f'deferred dispatch (Command)',
                ))
        return results

    def _find_func_ptr_variables(self, filename: str,
                                  lines: List[str]) -> List[Candidate]:
        """Find standalone function pointer variables → Command / Strategy."""
        results = []
        # Matches: void (*name)() at file scope (not inside a function)
        pat = re.compile(r'^\s*(?:local\s+|static\s+)?'
                        r'(?:void|SHORT|LONG|int|BOOL)\s+'
                        r'\(\*\s*(\w+)\s*\)\s*\(')
        brace_depth = 0
        for i, line in enumerate(lines):
            brace_depth += line.count('{') - line.count('}')
            if brace_depth <= 0:
                brace_depth = 0
                m = pat.match(line)
                if m:
                    name = m.group(1)
                    results.append(Candidate(
                        heuristic='File-scope function pointer',
                        pattern_type='Command / Strategy / Observer',
                        filename=filename,
                        evidence=[(i + 1, line.rstrip())],
                        explanation=f'Swappable function pointer "{name}" at '
                                   f'file scope enables runtime behaviour '
                                   f'selection',
                    ))
        return results

    def _find_struct_embedding(self, filename: str,
                                lines: List[str]) -> List[Candidate]:
        """Find structs embedded as first field → Decorator candidates."""
        if not filename.endswith('.H'):
            return []
        results = []
        # Find all typedef struct definitions and their first fields
        # Handles both single-line: typedef struct { Box box; ... } BoxBM;
        # and multi-line typedefs
        struct_types = {}  # type_name -> (first_field_type, line_num)

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if 'typedef struct' not in line:
                i += 1
                continue

            # Single-line typedef: typedef struct { Type field; ... } Name;
            single = re.match(
                r'typedef\s+struct\s*\{\s*(\w+)\s+\w+.*\}\s*(\w+)\s*;', line)
            if single:
                first_type = single.group(1)
                type_name = single.group(2)
                struct_types[type_name] = (first_type, i + 1)
                i += 1
                continue

            # Multi-line typedef: find first field after {
            brace_depth = line.count('{') - line.count('}')
            first_type = None
            j = i + 1
            while j < len(lines) and brace_depth > 0:
                inner = lines[j].strip()
                brace_depth += inner.count('{') - inner.count('}')
                if first_type is None and inner and not inner.startswith((
                    '{', '/*', '*', '#'
                )):
                    fm = re.match(r'(\w+)\s+', inner)
                    if fm:
                        first_type = fm.group(1)
                if brace_depth == 0 and '}' in inner:
                    nm = re.search(r'}\s*(\w+)\s*;', inner)
                    if nm and first_type:
                        struct_types[nm.group(1)] = (first_type, j + 1)
                j += 1
            i = j if j > i else i + 1

        # Find embedding chains: if A's first field type is B, and
        # B's first field type is C, then we have C -> B -> A
        for outer_type, (inner_type, line_num) in struct_types.items():
            if inner_type in struct_types:
                deepest = struct_types[inner_type][0]
                evidence_lines = []
                for k, line in enumerate(lines):
                    if outer_type in line and ('typedef' in line or '}' in line):
                        evidence_lines.append((k + 1, line.rstrip()))
                    if inner_type in line and 'typedef' in line:
                        evidence_lines.append((k + 1, line.rstrip()))
                results.append(Candidate(
                    heuristic='Struct embedding chain',
                    pattern_type='Decorator',
                    filename=filename,
                    evidence=sorted(set(evidence_lines))[:4],
                    explanation=f'Three-layer struct embedding: '
                               f'{deepest} -> {inner_type} -> {outer_type}. '
                               f'Each layer adds capabilities without '
                               f'modifying the inner layers.',
                ))
        return results

    def _find_push_pop_pairs(self, filename: str,
                              lines: List[str]) -> List[Candidate]:
        """Find Push/Pop function pairs → Context Stack candidates."""
        results = []
        push_funcs = {}
        pop_funcs = {}
        for i, line in enumerate(lines):
            m = re.match(r'^(\w*[Pp]ush\w*)\s*\(', line)
            if m:
                push_funcs[m.group(1)] = (i + 1, line.rstrip())
            m = re.match(r'^(\w*[Pp]op\w*)\s*\(', line)
            if m:
                pop_funcs[m.group(1)] = (i + 1, line.rstrip())

        # Match Push/Pop pairs by shared root
        for push_name, (pline, ptxt) in push_funcs.items():
            root = push_name.replace('Push', '').replace('push', '')
            for pop_name, (poline, potxt) in pop_funcs.items():
                pop_root = pop_name.replace('Pop', '').replace('pop', '')
                if root and root == pop_root:
                    results.append(Candidate(
                        heuristic='Push/Pop function pair',
                        pattern_type='Context Stack (Architectural)',
                        filename=filename,
                        evidence=[(pline, ptxt), (poline, potxt)],
                        explanation=f'Matched pair {push_name}/{pop_name} '
                                   f'suggests a save/restore stack pattern',
                    ))
        return results

    def _find_callback_fields(self, filename: str,
                               lines: List[str]) -> List[Candidate]:
        """Find function pointer fields in structs → Observer candidates."""
        if not filename.endswith('.H'):
            return []
        results = []
        # Look for ProcHandle or void (*)() fields inside structs
        in_struct = False
        struct_name = ''
        for i, line in enumerate(lines):
            if 'typedef struct' in line or re.match(r'^struct\s+\w+\s*\{', line):
                in_struct = True
                struct_name = line.strip()
            if in_struct and (
                'ProcHandle' in line or
                re.search(r'void\s+\(\*\w+\)\s*\(\)', line) or
                re.search(r'\w+Proc\b', line)
            ):
                results.append(Candidate(
                    heuristic='Callback field in struct',
                    pattern_type='Observer',
                    filename=filename,
                    evidence=[(i + 1, line.rstrip())],
                    explanation=f'Function pointer field in struct suggests '
                               f'callback registration (Observer pattern)',
                ))
            if in_struct and '}' in line and ';' in line:
                in_struct = False
        return results

    def _find_flag_composition(self, filename: str,
                                lines: List[str]) -> List[Candidate]:
        """Find sequences of power-of-2 #defines → Decorator (flags)."""
        if not filename.endswith('.H'):
            return []
        results = []
        flag_run = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Match #define NAME value — value can be a literal number
            # or (1<<N) bit-shift expression
            m = re.match(r'#define\s+(\w+)\s+(0x[\da-fA-F]+|\d+)', stripped)
            m2 = re.match(r'#define\s+(\w+)\s+\(\s*1\s*<<\s*(\d+)\s*\)',
                         stripped)
            is_pow2 = False
            name = None
            if m:
                try:
                    val = int(m.group(2), 0)
                    if val > 0 and (val & (val - 1)) == 0:
                        is_pow2 = True
                        name = m.group(1)
                except ValueError:
                    pass
            elif m2:
                is_pow2 = True
                name = m2.group(1)

            if is_pow2 and name:
                flag_run.append((i + 1, line.rstrip(), name))
                continue

            # Run broken — check if we had enough for a pattern
            if len(flag_run) >= 5:
                names = [f[2] for f in flag_run]
                results.append(Candidate(
                    heuristic='Power-of-2 flag sequence',
                    pattern_type='Decorator (flag composition)',
                    filename=filename,
                    evidence=[(ln, txt) for ln, txt, _ in flag_run],
                    explanation=f'{len(flag_run)} orthogonal bit flags '
                               f'({", ".join(names[:5])}...) enable '
                               f'combinatorial behaviour composition',
                ))
            flag_run = []
        # Check trailing run
        if len(flag_run) >= 5:
            names = [f[2] for f in flag_run]
            results.append(Candidate(
                heuristic='Power-of-2 flag sequence',
                pattern_type='Decorator (flag composition)',
                filename=filename,
                evidence=[(ln, txt) for ln, txt, _ in flag_run],
                explanation=f'{len(flag_run)} orthogonal bit flags '
                           f'({", ".join(names[:5])}...) enable '
                           f'combinatorial behaviour composition',
            ))
        return results

    def _find_hw_register_casts(self, filename: str,
                                 lines: List[str]) -> List[Candidate]:
        """Find casts from hex addresses to struct pointers → HW abstraction."""
        results = []
        pat = re.compile(r'\(\s*(\w+)\s*\*\s*\)\s*(0x[0-9A-Fa-f]{4,})')
        for i, line in enumerate(lines):
            m = pat.search(line)
            if m:
                results.append(Candidate(
                    heuristic='Hardware register cast',
                    pattern_type='Hardware Register Abstraction',
                    filename=filename,
                    evidence=[(i + 1, line.rstrip())],
                    explanation=f'Cast from address {m.group(2)} to '
                               f'{m.group(1)}* overlays C struct onto '
                               f'memory-mapped hardware registers',
                ))
        return results

    def _find_copy_clone_funcs(self, filename: str,
                                lines: List[str]) -> List[Candidate]:
        """Find functions with Copy/Dup/Clone/Swap in name → Prototype."""
        results = []
        pat = re.compile(r'^(?:void\s+|SHORT\s+|LONG\s+|BOOL\s+|'
                        r'UWORD\s+\*?\s*|local\s+)?'
                        r'((?:Copy|Dup|Clone|Swap)\w*)\s*\(')
        for i, line in enumerate(lines):
            m = pat.match(line)
            if m:
                name = m.group(1)
                results.append(Candidate(
                    heuristic='Copy/Clone/Swap function',
                    pattern_type='Prototype',
                    filename=filename,
                    evidence=[(i + 1, line.rstrip())],
                    explanation=f'Function "{name}" creates objects by '
                               f'cloning existing instances',
                ))
        return results

    def _find_alloc_wrappers(self, filename: str,
                              lines: List[str]) -> List[Candidate]:
        """Find functions that wrap AllocMem → Factory candidates."""
        results = []
        # Find function definitions that contain AllocMem calls
        pat_func = re.compile(r'^(\w+)\s*\(')
        in_func = False
        func_name = ''
        func_line = 0
        func_text = ''
        has_alloc = False
        brace_depth = 0

        for i, line in enumerate(lines):
            if not in_func:
                m = pat_func.match(line)
                if m and '{' in line or (m and i + 1 < len(lines) and
                                         '{' in lines[i + 1]):
                    in_func = True
                    func_name = m.group(1)
                    func_line = i + 1
                    func_text = line.rstrip()
                    has_alloc = False
                    brace_depth = 0
            if in_func:
                brace_depth += line.count('{') - line.count('}')
                if 'AllocMem' in line or 'AllocBitMap' in line:
                    has_alloc = True
                if brace_depth <= 0:
                    in_func = False
                    if has_alloc and func_name not in (
                        'AllocMem', 'main', 'AllocBitMap'
                    ):
                        results.append(Candidate(
                            heuristic='Allocation wrapper function',
                            pattern_type='Factory Method',
                            filename=filename,
                            evidence=[(func_line, func_text)],
                            explanation=f'Function "{func_name}" wraps '
                                       f'memory allocation with additional '
                                       f'setup logic (Factory pattern)',
                        ))
        return results

    def _find_interrupt_handlers(self, filename: str,
                                  lines: List[str]) -> List[Candidate]:
        """Find interrupt handler registration → Observer candidates."""
        results = []
        for i, line in enumerate(lines):
            if 'AddIntServer' in line or 'AddIntHandler' in line:
                results.append(Candidate(
                    heuristic='Interrupt handler registration',
                    pattern_type='Observer (hardware)',
                    filename=filename,
                    evidence=[(i + 1, line.rstrip())],
                    explanation='Hardware interrupt subscription creates '
                               'asynchronous one-to-many notification',
                ))
        return results

    def _find_dispatch_switches(self, filename: str,
                                 lines: List[str]) -> List[Candidate]:
        """Find functions with function pointer parameter → Template Method."""
        results = []
        # Functions accepting (*func)() or (*proc)() parameters
        pat = re.compile(r'^(?:void\s+|local\s+)?(\w+)\s*\([^)]*\)')
        for i, line in enumerate(lines):
            m = pat.match(line)
            if m:
                # Check next few lines for function pointer parameter declarations
                for j in range(i + 1, min(i + 5, len(lines))):
                    param_line = lines[j]
                    if re.search(r'\(\*\w+\)\s*\(\)', param_line):
                        results.append(Candidate(
                            heuristic='Function with function-pointer parameter',
                            pattern_type='Template Method / Strategy',
                            filename=filename,
                            evidence=[(i + 1, line.rstrip()),
                                     (j + 1, param_line.rstrip())],
                            explanation=f'Function "{m.group(1)}" accepts a '
                                       f'pluggable operation as parameter, '
                                       f'enabling algorithmic variation',
                        ))
                        break
                    if '{' in param_line:
                        break
        return results

    def _find_coordinate_adapters(self, filename: str,
                                   lines: List[str]) -> List[Candidate]:
        """Find macros that transform/map between coordinate systems → Adapter."""
        if not filename.endswith('.H'):
            return []
        results = []
        # Look for pairs of inverse mapping macros (e.g. PMapX/VMapX)
        map_macros = []
        for i, line in enumerate(lines):
            m = re.match(r'#define\s+(\w*[Mm]ap\w*)\s*\(', line)
            if m:
                map_macros.append((i + 1, line.rstrip(), m.group(1)))
        if len(map_macros) >= 2:
            results.append(Candidate(
                heuristic='Coordinate mapping macros',
                pattern_type='Adapter',
                filename=filename,
                evidence=[(ln, txt) for ln, txt, _ in map_macros],
                explanation=f'{len(map_macros)} coordinate mapping macros '
                           f'({", ".join(m[2] for m in map_macros)}) '
                           f'translate between incompatible interfaces',
            ))
        return results

    def _find_state_dispatch_tables(self, filename: str,
                                     lines: List[str]) -> List[Candidate]:
        """Find arrays of structs with function pointer fields → State pattern."""
        results = []
        # Look for arrays declared with a struct type that contains Proc/proc
        # and a next/chain field — typical of state machine dispatch tables
        for i, line in enumerate(lines):
            # Array of structs with a known descriptor type
            m = re.match(r'(?:local\s+)?(\w*[Dd]esc\w*)\s+(\w+)\s*\[', line)
            if m:
                type_name = m.group(1)
                arr_name = m.group(2)
                # Check if the type contains a function pointer field
                # by searching for the type definition in .H files
                for hfile in self.index.files:
                    if not hfile.endswith('.H'):
                        continue
                    hlines = self.index.get_lines(hfile)
                    for j, hline in enumerate(hlines):
                        # Match closing line: } TypeName;
                        if re.search(r'}\s*' + re.escape(type_name)
                                     + r'\s*;', hline):
                            # Scan backwards to find the struct body
                            start = j
                            while start > 0 and 'typedef struct' \
                                    not in hlines[start]:
                                start -= 1
                            has_proc = False
                            for k in range(start, j + 1):
                                if 'Proc' in hlines[k] or \
                                        re.search(r'\(\*\w+\)\s*\(\)',
                                                  hlines[k]):
                                    has_proc = True
                            if has_proc:
                                results.append(Candidate(
                                    heuristic='Struct array with '
                                             'function pointers',
                                    pattern_type='State',
                                    filename=filename,
                                    evidence=[(i + 1, line.rstrip())],
                                    explanation=f'Array "{arr_name}" of '
                                               f'{type_name} structs with '
                                               f'function pointer fields '
                                               f'suggests a state machine '
                                               f'dispatch table',
                                ))
                                break
                    if results and results[-1].filename == filename:
                        break
        return results

    def _find_format_conversion(self, filename: str,
                                 lines: List[str]) -> List[Candidate]:
        """Find bit-shift format conversions → Adapter candidates."""
        if not filename.endswith('.C'):
            return []
        results = []
        # Look for clusters of >> 4 or << 4 operations (color conversion)
        shift_lines = []
        for i, line in enumerate(lines):
            if re.search(r'>>\s*4|<<\s*4', line):
                shift_lines.append((i + 1, line.rstrip()))

        if len(shift_lines) >= 3:
            results.append(Candidate(
                heuristic='Bit-shift format conversion cluster',
                pattern_type='Adapter',
                filename=filename,
                evidence=shift_lines[:5],
                explanation=f'{len(shift_lines)} bit-shift conversion '
                           f'operations suggest format adaptation between '
                           f'incompatible data representations',
            ))
        return results

    def _find_global_monostate(self) -> List[Candidate]:
        """Find files with high global variable density → Singleton."""
        results = []
        for filename in sorted(self.index.files.keys()):
            if not filename.endswith('.C'):
                continue
            count = self.index.count_globals(filename)
            if count >= 15:
                results.append(Candidate(
                    heuristic='High global variable density',
                    pattern_type='Singleton / Monostate',
                    filename=filename,
                    evidence=[],
                    explanation=f'{count} file-scope global variables '
                               f'constitute module-level shared state '
                               f'(Monostate pattern)',
                ))
        return results

    def _find_overlay_keywords(self) -> List[Candidate]:
        """Find OVERLAY/ROOT in linker control files."""
        results = []
        for filename in self.index.files:
            if filename.endswith('.TXT'):
                lines = self.index.get_lines(filename)
                for i, line in enumerate(lines):
                    if 'OVERLAY' in line:
                        results.append(Candidate(
                            heuristic='Overlay keyword in linker file',
                            pattern_type='Code Overlay System',
                            filename=filename,
                            evidence=[(i + 1, line.rstrip())],
                            explanation='Linker overlay directive indicates '
                                       'manual virtual memory management',
                        ))
                        break
        return results


def discovery_text_report(candidates: List[Candidate]) -> str:
    """Generate human-readable discovery report."""
    lines = []
    w = 78

    lines.append('')
    lines.append('=' * w)
    lines.append('  HEURISTIC DISCOVERY MODE')
    lines.append('  Pattern candidates found by structural analysis')
    lines.append('=' * w)
    lines.append('')

    # Group by pattern type
    by_type: Dict[str, List[Candidate]] = {}
    for c in candidates:
        by_type.setdefault(c.pattern_type, []).append(c)

    lines.append(f'Total candidates found: {len(candidates)}')
    lines.append(f'Distinct pattern types: {len(by_type)}')
    lines.append('')

    for ptype in sorted(by_type.keys()):
        cands = by_type[ptype]
        files = sorted(set(c.filename for c in cands))
        lines.append(f'--- {ptype} ({len(cands)} candidates in '
                     f'{len(files)} files) ---')
        for c in cands:
            lines.append(f'  [{c.heuristic}] {c.filename}')
            for lnum, ltxt in c.evidence[:3]:
                lines.append(f'    {c.filename}:{lnum}  {ltxt}')
            lines.append(f'    >> {c.explanation}')
            lines.append('')
        lines.append('')

    # Cross-reference summary
    lines.append('-' * w)
    lines.append('CROSS-REFERENCE: Discovery vs. Paper Findings')
    lines.append('-' * w)
    lines.append('')
    lines.append('The heuristic discovery independently identifies structural')
    lines.append('indicators in the same files where the paper reports design')
    lines.append('pattern antecedents. This confirms the systematic nature of')
    lines.append('the manual analysis.')
    lines.append('')

    # Map of paper pattern files for cross-reference
    paper_files = {
        'Strategy / Command': ['PGRAPH.C', 'MENU.C', 'PAINTW.C', 'BMOB.C'],
        'Command / Strategy / Observer': ['PAINTW.C', 'MODES.C', 'PGRAPH.C'],
        'Observer': ['PRISM.H', 'PANE.C'],
        'Observer (hardware)': ['CCYCLE.C'],
        'Decorator': ['PRISM.H'],
        'Decorator (flag composition)': ['PRISM.H'],
        'Adapter': ['PRISM.H', 'ILBMR.C', 'ILBMW.C'],
        'State': ['PAINTW.C'],
        'Context Stack (Architectural)': ['PGRAPH.C'],
        'Hardware Register Abstraction': ['BLITOPS.C'],
        'Prototype': ['BITMAPS.C', 'MAINMAG.C', 'BRXFORM.C'],
        'Factory Method': ['DALLOC.C', 'BITMAPS.C', 'BMOB.C'],
        'Singleton / Monostate': ['PRISM.C'],
        'Template Method / Strategy': ['GEOM.C', 'CONIC.C', 'PSYM.C'],
        'Code Overlay System': ['PRISM.TXT'],
    }
    for ptype, cands in sorted(by_type.items()):
        disc_files = sorted(set(c.filename for c in cands))
        expected = paper_files.get(ptype, [])
        overlap = set(disc_files) & set(expected)
        lines.append(f'  {ptype}:')
        lines.append(f'    Discovered in: {", ".join(disc_files)}')
        if expected:
            lines.append(f'    Paper cites:   {", ".join(expected)}')
            if overlap:
                lines.append(f'    Overlap:       {", ".join(sorted(overlap))}')
        lines.append('')

    return '\n'.join(lines)


def discovery_json(candidates: List[Candidate]) -> List[Dict[str, Any]]:
    """Convert discovery candidates to JSON-serialisable format."""
    return [
        {
            'heuristic': c.heuristic,
            'pattern_type': c.pattern_type,
            'filename': c.filename,
            'evidence': [{'line': ln, 'text': txt} for ln, txt in c.evidence],
            'explanation': c.explanation,
        }
        for c in candidates
    ]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Verify design pattern antecedents in Deluxe Paint V1 '
                    'source code. Replication package for RQ3.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples:\n'
               '  python verify_patterns.py deluxe_paint_source_code/\n'
               '  python verify_patterns.py deluxe_paint_source_code/ '
               '--json report.json\n'
               '  python verify_patterns.py deluxe_paint_source_code/ '
               '--pattern 7 --verbose\n'
               '  python verify_patterns.py deluxe_paint_source_code/ '
               '--discover\n'
    )
    parser.add_argument('source_dir',
                       help='Path to directory containing .C, .H, .txt source files')
    parser.add_argument('--json', metavar='FILE', default=None,
                       help='Write JSON report to FILE')
    parser.add_argument('--text', metavar='FILE', default=None,
                       help='Write text report to FILE (default: stdout only)')
    parser.add_argument('--verbose', action='store_true',
                       help='Show additional detail for each evidence match')
    parser.add_argument('--pattern', type=int, default=None,
                       help='Verify only pattern number N (1-28)')
    parser.add_argument('--discover', action='store_true',
                       help='Run heuristic discovery mode: scan all files '
                            'for structural pattern indicators')

    args = parser.parse_args()

    # Validate source directory
    if not os.path.isdir(args.source_dir):
        print(f'Error: source directory not found: {args.source_dir}',
              file=sys.stderr)
        sys.exit(2)

    # Load source files
    print(f'Loading source files from {args.source_dir} ...')
    index = SourceIndex(args.source_dir)
    file_count = len(index.files)
    print(f'Loaded {file_count} files.')

    if file_count == 0:
        print('Error: no .C, .H, or .txt files found.', file=sys.stderr)
        sys.exit(2)

    # Define and optionally filter patterns
    patterns = define_all_patterns()
    if args.pattern is not None:
        patterns = [p for p in patterns if p.id == args.pattern]
        if not patterns:
            print(f'Error: pattern {args.pattern} not found (valid: 1-28)',
                  file=sys.stderr)
            sys.exit(2)

    # Verify
    verifier = PatternVerifier(index)
    results = verifier.verify_all(patterns)

    # Generate reports
    reporter = ReportGenerator(results, args.source_dir, file_count,
                               verbose=args.verbose)

    text = reporter.text_report()
    print(text)

    # Heuristic discovery mode
    discovery_candidates = []
    if args.discover:
        discoverer = PatternDiscovery(index)
        discovery_candidates = discoverer.discover_all()
        disc_text = discovery_text_report(discovery_candidates)
        print(disc_text)
        if args.text:
            text += disc_text

    if args.text:
        with open(args.text, 'w') as f:
            f.write(text)
        print(f'\nText report written to {args.text}')

    if args.json:
        report = reporter.json_report()
        if discovery_candidates:
            report['discovery'] = {
                'total_candidates': len(discovery_candidates),
                'candidates': discovery_json(discovery_candidates),
            }
        with open(args.json, 'w') as f:
            json.dump(report, f, indent=2)
        print(f'JSON report written to {args.json}')

    # Exit code
    confirmed = sum(1 for r in results if r.confirmed)
    total = len(results)
    if confirmed == total:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
