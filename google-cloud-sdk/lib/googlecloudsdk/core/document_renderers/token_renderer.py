# -*- coding: utf-8 -*- #
# Copyright 2017 Google LLC. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cloud SDK markdown document token renderer.

This is different from the other renderers:

(1) The output is a list of (token, text) tuples returned by
    TokenRenderer.Finish().
(2) A token is an empty object that conveys font style and embellishment by
    convention using the token name. Callers set up a style sheet indexed by
    tokens to control how the embellishments are rendered, e.g. color.
(3) The rendering is constrained by width and height.

Tokens generated by this module:

  Token.Markdown.Bold: bold text
  Token.Markdown.BoldItalic: bold+italic text
  Token.Markdown.Code: code text for command line examples
  Token.Markdown.Definition: definition list item (flag or subcommand or choice)
  Token.Markdown.Italic: italic text
  Token.Markdown.Normal: normal text
  Token.Markdown.Section: section header
  Token.Markdown.Truncated: the last token => indicates truncation
  Token.Markdown.Value: definition list item value (flag value)

The Token objects self-define on first usage. Don't champion this pattern in the
Cloud SDK.

Usage:

  from six.moves import StringIO

  from googlecloudsdk.core.document_renderers import token_renderer
  from googlecloudsdk.core.document_renderers import render_document

  markdown = <markdown document string>
  tokens = render_document.MarkdownRenderer(
      token_renderer.TokenRenderer(width=W, height=H),
      StringIO(markdown)).Run()
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import unicode_literals

import re

from googlecloudsdk.core.console import console_attr
from googlecloudsdk.core.document_renderers import renderer

from prompt_toolkit.token import Token


class TokenRenderer(renderer.Renderer):
  """Renders markdown to a list of lines where each line is a list of Tokens.

  Attributes:
    _attr: console_attr.ConsoleAttr object.
    _bullet: List of bullet characters indexed by list level modulo #bullets.
    _compact: Compact representation if True. Saves rendering real estate.
    _csi: The control sequence indicator character. Token does not
      have control sequences. This renderer uses them internally to manage
      font styles and attributes (bold, code, italic).
    _current_token_type: current default Token.Markdown.* type
    _fill: The number of characters in the current output line.
    _height: The height of the output window, 0 to disable height checks.
    _ignore_paragraph: Ignore paragraph markdown until the next non-space
      _AddToken.
    _ignore_width: True if the next output word should ignore _width.
    _indent: List of left indentations in characters indexed by _level.
    _level: The section or list level counting from 0.
    _tokens: The list of output tokens
    _truncated: The number of output lines exceeded the output height.
    _rows: current rows in table
  """
  # Internal inline embellishments are 2 character sequences
  # <CSI><EMBELLISHMENT>. The embellishment must be an alpha character
  # to make the display width helpers work properly.
  CSI = '\0'  # Won't clash with markdown text input.
  EMBELLISHMENTS = {
      'B': Token.Markdown.Bold,
      'C': Token.Markdown.Code,
      'I': Token.Markdown.Italic,
      'N': Token.Markdown.Normal,
      'Z': Token.Markdown.BoldItalic,
  }
  INDENT = 4
  SPLIT_INDENT = 2
  TOKEN_TYPE_INDEX = 0
  TOKEN_TEXT_INDEX = 1

  class Indent(object):
    """Hanging indent stack."""

    def __init__(self, compact=True):
      self.indent = 0 if compact else TokenRenderer.INDENT
      self.hanging_indent = self.indent

  def __init__(self, height=0, encoding='utf-8', compact=True, **kwargs):
    super(TokenRenderer, self).__init__(**kwargs)
    self._attr = console_attr.GetConsoleAttr(encoding=encoding)
    self._csi = self.CSI
    self._attr._csi = self._csi  # pylint: disable=protected-access
    self._bullet = self._attr.GetBullets()
    self._compact = compact
    self._fill = 0
    self._current_token_type = Token.Markdown.Normal
    self._height = height
    self._ignore_paragraph = False
    self._ignore_width = False
    self._indent = [self.Indent(compact)]
    self._level = 0
    self._lines = []
    self._tokens = []
    self._truncated = False
    self._rows = []

  def _Truncate(self, tokens, overflow):
    """Injects a truncation indicator token and rejects subsequent tokens.

    Args:
      tokens: The last line of tokens at the output height. The part of the
        line within the output width will be visible, modulo the trailing
        truncation marker token added here.
      overflow: If not None then this is a (word, available) tuple from Fill()
        where word caused the line width overflow and available is the number of
        characters available in the current line before ' '+word would be
        appended.

    Returns:
      A possibly altered list of tokens that form the last output line.
    """
    self._truncated = True
    marker_string = '...'
    marker_width = len(marker_string)
    marker_token = (Token.Markdown.Truncated, marker_string)
    if tokens and overflow:
      word, available = overflow  # pylint: disable=unpacking-non-sequence
      if marker_width == available:
        # Exactly enough space for the marker.
        pass
      elif (marker_width + 1) <= available:
        # The marker can replace the trailing characters in the overflow word.
        word = ' ' + self._UnFormat(word)[:available-marker_width-1]
        tokens.append((self._current_token_type, word))
      else:
        # Truncate the token list so the marker token can fit.
        truncated_tokens = []
        available = self._width
        for token in tokens:
          word = token[self.TOKEN_TEXT_INDEX]
          width = self._attr.DisplayWidth(word)
          available -= width
          if available <= marker_width:
            trim = marker_width - available
            if trim:
              word = word[:-trim]
            truncated_tokens.append((token[self.TOKEN_TYPE_INDEX], word))
            break
          truncated_tokens.append(token)
        tokens = truncated_tokens
    tokens.append(marker_token)
    return tokens

  def _NewLine(self, overflow=None):
    """Adds the current token list to the line list.

    Args:
      overflow: If not None then this is a (word, available) tuple from Fill()
        where word caused the line width overflow and available is the number of
        characters available in the current line before ' '+word would be
        appended.
    """
    tokens = self._tokens
    self._tokens = []
    if self._truncated or not tokens and self._compact:
      return
    if self._lines:
      # Delete trailing space.
      while (self._lines[-1] and
             self._lines[-1][-1][self.TOKEN_TEXT_INDEX].isspace()):
        self._lines[-1] = self._lines[-1][:-1]
    if self._height and (len(self._lines) + int(bool(tokens))) >= self._height:
      tokens = self._Truncate(tokens, overflow)
    self._lines.append(tokens)

  def _MergeOrAddToken(self, text, token_type):
    """Merges text if the previous token_type matches or appends a new token."""
    if not text:
      return
    if (not self._tokens or
        self._tokens[-1][self.TOKEN_TYPE_INDEX] != token_type):
      self._tokens.append((token_type, text))
    elif self._tokens[-1][self.TOKEN_TYPE_INDEX] == Token.Markdown.Section:
      # A section header with no content.
      prv_text = self._tokens[-1][self.TOKEN_TEXT_INDEX]
      prv_indent = re.match('( *)', prv_text).group(1)
      new_indent = re.match('( *)', text).group(1)
      if prv_indent == new_indent:
        # Same indentation => discard the previous empty section.
        self._tokens[-1] = (token_type, text)
      else:
        # Insert newline to separate previous header from the new one.
        self._NewLine()
        self._tokens.append((token_type, text))
    else:
      self._tokens[-1] = (token_type,
                          self._tokens[-1][self.TOKEN_TEXT_INDEX] + text)

  def _AddToken(self, text, token_type=None):
    """Appends a (token_type, text) tuple to the current line."""
    if text and not text.isspace():
      self._ignore_paragraph = False
    if not token_type:
      token_type = self._current_token_type
    if self._csi not in text:
      self._MergeOrAddToken(text, token_type)
    else:
      i = 0
      while True:
        j = text.find(self._csi, i)
        if j < 0:
          self._MergeOrAddToken(text[i:], token_type)
          break
        self._MergeOrAddToken(text[i:j], token_type)
        token_type = self.EMBELLISHMENTS[text[j + 1]]
        self._current_token_type = token_type
        i = j + 2

  def _UnFormat(self, text):
    """Returns text with all inline formatting stripped."""
    if self._csi not in text:
      return text
    stripped = []
    i = 0
    while i < len(text):
      j = text.find(self._csi, i)
      if j < 0:
        stripped.append(text[i:])
        break
      stripped.append(text[i:j])
      i = j + 2
    return ''.join(stripped)

  def _AddDefinition(self, text):
    """Appends a definition list definition item to the current line."""
    text = self._UnFormat(text)
    parts = text.split('=', 1)
    self._AddToken(parts[0], Token.Markdown.Definition)
    if len(parts) > 1:
      self._AddToken('=', Token.Markdown.Normal)
      self._AddToken(parts[1], Token.Markdown.Value)
    self._NewLine()

  def _Flush(self):
    """Flushes the current collection of Fill() lines."""
    self._ignore_width = False
    if self._fill:
      self._NewLine()
      self.Content()
      self._fill = 0

  def _SetIndent(self, level, indent=0, hanging_indent=None):
    """Sets the markdown list level and indentations.

    Args:
      level: int, The desired markdown list level.
      indent: int, The new indentation.
      hanging_indent: int, The hanging indentation. This is subtracted from the
        prevailing indent to decrease the indentation of the next input line
        for this effect:
            HANGING INDENT ON THE NEXT LINE
               PREVAILING INDENT
               ON SUBSEQUENT LINES
    """
    if self._level < level:
      # The level can increase by 1 or more. Loop through each so that
      # intervening levels are handled the same.
      while self._level < level:
        prev_level = self._level
        self._level += 1
        if self._level >= len(self._indent):
          self._indent.append(self.Indent())
        self._indent[self._level].indent = (
            self._indent[prev_level].indent + indent)
        if (self._level > 1 and
            self._indent[prev_level].hanging_indent ==
            self._indent[prev_level].indent):
          # Bump the indent by 1 char for nested indentation. Top level looks
          # fine (aesthetically) without it.
          self._indent[self._level].indent += 1
        self._indent[self._level].hanging_indent = (
            self._indent[self._level].indent)
        if hanging_indent is not None:
          # Adjust the hanging indent if specified.
          self._indent[self._level].hanging_indent -= hanging_indent
    else:
      # Decreasing level just sets the indent stack level, no state to clean up.
      self._level = level
      if hanging_indent is not None:
        # Change hanging indent on existing level.
        self._indent[self._level].indent = (
            self._indent[self._level].hanging_indent + hanging_indent)

  def Example(self, line):
    """Displays line as an indented example.

    Args:
      line: The example line text.
    """
    self._fill = self._indent[self._level].indent + self.INDENT
    self._AddToken(' ' * self._fill + line, Token.Markdown.Normal)
    self._NewLine()
    self.Content()
    self._fill = 0

  def Fill(self, line):
    """Adds a line to the output, splitting to stay within the output width.

    This is close to textwrap.wrap() except that control sequence characters
    don't count in the width computation.

    Args:
      line: The text line.
    """
    self.Blank()
    for word in line.split():
      if not self._fill:
        if self._level or not self._compact:
          self._fill = self._indent[self._level].indent - 1
        else:
          self._level = 0
        self._AddToken(' ' * self._fill)
      width = self._attr.DisplayWidth(word)
      available = self._width - self._fill
      if (width + 1) >= available and not self._ignore_width:
        self._NewLine(overflow=(word, available))
        self._fill = self._indent[self._level].indent
        self._AddToken(' ' * self._fill)
      else:
        self._ignore_width = False
        if self._fill:
          self._fill += 1
          self._AddToken(' ')
      self._fill += width
      self._AddToken(word)

  def Finish(self):
    """Finishes all output document rendering."""
    self._Flush()
    self.Font()
    return self._lines

  def Font(self, attr=None):
    """Returns the font embellishment control sequence for attr.

    Args:
      attr: None to reset to the default font, otherwise one of renderer.BOLD,
        renderer.ITALIC, or renderer.CODE.

    Returns:
      The font embellishment control sequence.
    """
    if attr is None:
      self._font = 0
    else:
      mask = 1 << attr
      self._font ^= mask
    font = self._font & ((1 << renderer.BOLD) |
                         (1 << renderer.CODE) |
                         (1 << renderer.ITALIC))
    if font & (1 << renderer.CODE):
      embellishment = 'C'
    elif font == ((1 << renderer.BOLD) | (1 << renderer.ITALIC)):
      embellishment = 'Z'
    elif font == (1 << renderer.BOLD):
      embellishment = 'B'
    elif font == (1 << renderer.ITALIC):
      embellishment = 'I'
    else:
      embellishment = 'N'
    return self._csi + embellishment

  def Heading(self, level, heading):
    """Renders a heading.

    Args:
      level: The heading level counting from 1.
      heading: The heading text.
    """
    if level == 1 and heading.endswith('(1)'):
      # Ignore man page TH.
      return
    self._Flush()
    self.Line()
    self.Font()
    if level > 2:
      indent = '  ' * (level - 2)
      self._AddToken(indent)
      if self._compact:
        self._ignore_paragraph = True
        self._fill += len(indent)
    self._AddToken(heading, Token.Markdown.Section)
    if self._compact:
      self._ignore_paragraph = True
      self._fill += self._attr.DisplayWidth(heading)
    else:
      self._NewLine()
    self.Blank()
    self._level = 0
    self._rows = []

  def Line(self):
    """Renders a paragraph separating line."""
    if self._ignore_paragraph:
      return
    self._Flush()
    if not self.HaveBlank():
      self.Blank()
      self._NewLine()

  def List(self, level, definition=None, end=False):
    """Renders a bullet or definition list item.

    Args:
      level: The list nesting level, 0 if not currently in a list.
      definition: Bullet list if None, definition list item otherwise.
      end: End of list if True.
    """
    self._Flush()
    if not level:
      self._level = level
    elif end:
      # End of list.
      self._SetIndent(level)
    elif definition is not None:
      # Definition list item.
      if definition:
        self._SetIndent(level, indent=4, hanging_indent=3)
        self._AddToken(' ' * self._indent[level].hanging_indent)
        self._AddDefinition(definition)
      else:
        self._SetIndent(level, indent=1, hanging_indent=0)
        self.Line()
    else:
      # Bullet list item.
      indent = 2 if level > 1 else 4
      self._SetIndent(level, indent=indent, hanging_indent=2)
      self._AddToken(' ' * self._indent[level].hanging_indent +
                     self._bullet[(level - 1) % len(self._bullet)])
      self._fill = self._indent[level].indent + 1
      self._ignore_width = True

  def _SkipSpace(self, line, index):
    """Skip space characters starting at line[index].

    Args:
      line: The string.
      index: The starting index in string.

    Returns:
      The index in line after spaces or len(line) at end of string.
    """
    while index < len(line):
      c = line[index]
      if c != ' ':
        break
      index += 1
    return index

  def _SkipControlSequence(self, line, index):
    """Skip the control sequence at line[index].

    Args:
      line: The string.
      index: The starting index in string.

    Returns:
      The index in line after the control sequence or len(line) at end of
      string.
    """
    n = self._attr.GetControlSequenceLen(line[index:])
    if not n:
      n = 1
    return index + n

  def _SkipNest(self, line, index, open_chars='[(', close_chars=')]'):
    """Skip a [...] nested bracket group starting at line[index].

    Args:
      line: The string.
      index: The starting index in string.
      open_chars: The open nesting characters.
      close_chars: The close nesting characters.

    Returns:
      The index in line after the nesting group or len(line) at end of string.
    """
    nest = 0
    while index < len(line):
      c = line[index]
      index += 1
      if c in open_chars:
        nest += 1
      elif c in close_chars:
        nest -= 1
        if nest <= 0:
          break
      elif c == self._csi:
        index = self._SkipControlSequence(line, index)
    return index

  def _SplitWideSynopsisGroup(self, group, indent, running_width):
    """Splits a wide SYNOPSIS section group string._out.

    Args:
      group: The wide group string to split.
      indent: The prevailing left indent.
      running_width: The width of the line in progress.

    Returns:
      The running_width after the group has been split and written.
    """
    prev_delimiter = ' '
    while group:
      # Check split delimiters in order for visual emphasis.
      for delimiter in (' | ', ' : ', ' ', ','):
        part, _, remainder = group.partition(delimiter)
        w = self._attr.DisplayWidth(part)
        if ((running_width + len(prev_delimiter) + w) >= self._width or
            prev_delimiter != ',' and delimiter == ','):
          if delimiter != ',' and (indent +
                                   self.SPLIT_INDENT +
                                   len(prev_delimiter) +
                                   w) >= self._width:
            # The next delimiter may produce a smaller first part.
            continue
          if prev_delimiter == ',':
            self._AddToken(prev_delimiter)
            prev_delimiter = ' '
          if running_width != indent:
            running_width = indent + self.SPLIT_INDENT
            self._NewLine()
            self._AddToken(' ' * running_width)
        self._AddToken(prev_delimiter + part)
        running_width += len(prev_delimiter) + w
        prev_delimiter = delimiter
        group = remainder
        break
    return running_width

  def Synopsis(self, line):
    """Renders NAME and SYNOPSIS lines as a hanging indent.

    Collapses adjacent spaces to one space, deletes trailing space, and doesn't
    split top-level nested [...] or (...) groups. Also detects and does not
    count terminal control sequences.

    Args:
      line: The NAME or SYNOPSIS text.
    """
    # Split the line into token, token | token, and [...] groups.
    groups = []
    i = self._SkipSpace(line, 0)
    beg = i
    while i < len(line):
      c = line[i]
      if c == ' ':
        end = i
        i = self._SkipSpace(line, i)
        if i <= (len(line) - 1) and line[i] == '|' and line[i + 1] == ' ':
          i = self._SkipSpace(line, i + 1)
        else:
          groups.append(line[beg:end])
          beg = i
      elif c in '[(':
        i = self._SkipNest(line, i)
      elif c == self._csi:
        i = self._SkipControlSequence(line, i)
      else:
        i += 1
    if beg < len(line):
      groups.append(line[beg:])

    # Output the groups.
    indent = self._indent[0].indent - 1
    running_width = indent
    self._AddToken(' ' * running_width)
    indent += self.INDENT
    for group in groups:
      w = self._attr.DisplayWidth(group) + 1
      if (running_width + w) >= self._width:
        running_width = indent
        self._NewLine()
        self._AddToken(' ' * running_width)
        if (running_width + w) >= self._width:
          # The group is wider than the available width and must be split.
          running_width = self._SplitWideSynopsisGroup(
              group, indent, running_width)
          continue
      self._AddToken(' ' + group)
      running_width += w
    self._NewLine()
    self._NewLine()

  def TableLine(self, line, indent=0):
    """Adds an indented table line to the output.

    Args:
      line: The line to add. A newline will be added.
      indent: The number of characters to indent the table.
    """
    self._AddToken(indent * ' ' + line)
    self._NewLine()
