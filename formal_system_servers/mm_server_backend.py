#!/usr/bin/env python3
"""mmverify.py -- Proof verifier for the Metamath language
Copyright (C) 2002 Raph Levien raph (at) acm (dot) org
Copyright (C) David A. Wheeler and mmverify.py contributors

This program is free software distributed under the MIT license;
see the file LICENSE for full license information.
SPDX-License-Identifier: MIT

To run the program, type
  $ python3 mmverify.py set.mm --logfile set.log
and set.log will have the verification results.  One can also use bash
redirections and type '$ python3 mmverify.py < set.mm 2> set.log' but this
would fail in case 'set.mm' contains (directly or not) a recursive inclusion
statement $[ set.mm $] .

To get help on the program usage, type
  $ python3 mmverify.py -h

(nm 27-Jun-2005) mmverify.py requires that a $f hypothesis must not occur
after a $e hypothesis in the same scope, even though this is allowed by
the Metamath spec.  This is not a serious limitation since it can be
met by rearranging the hypothesis order.
(rl 2-Oct-2006) removed extraneous line found by Jason Orendorff
(sf 27-Jan-2013) ported to Python 3, added support for compressed proofs
and file inclusion
(bj 3-Apr-2022) streamlined code; obtained significant speedup (4x on set.mm)
by verifying compressed proofs without converting them to normal proof format;
added type hints
"""

import sys
import itertools
import pathlib
import argparse
import typing
import io
import re


verbosity = 0
Label = str
Var = str
Const = str
Stmttype = str  # can actually be only one of '$c', '$v', '$f', '$e', '$a', '$p', '$d', '$='
StringOption = typing.Optional[str]
Symbol = typing.Union[Var, Const]
Stmt = typing.List[Symbol]
Ehyp = Stmt
Fhyp = typing.Tuple[Var, Const]
Dv = typing.Tuple[Var, Var]
Assertion = typing.Tuple[typing.Set[Dv], typing.List[Fhyp], typing.List[Ehyp], Stmt]
FullStmt = typing.Tuple[Stmttype, typing.Union[Stmt, Assertion]]
# Actually, the second component of a FullStmt is a Stmt when its first
# component is '$e' or '$f' and an Assertion if its first component is '$a' or
# '$p', but this is a bit cumbersome to build it into the typing system.
# This explains the errors when static type checking (e.g., mypy): an
# if-statement determines in which case we are, but this is invisible to the
# type checker.

# Note: a script at github.com/metamath/set.mm removes from the following code
# the lines beginning with (spaces followed by) 'vprint(' using the command
#   $ sed -E '/^ *vprint\(/d' mmverify.py > mmverify.faster.py
# In order that mmverify.faster.py be valid, one must therefore not break
# 'vprint' commands over multiple lines, nor have indented blocs containing
# only vprint lines (this would create ill-indented files).


class MMError(Exception):
    """Class of Metamath errors."""
    pass


class MMKeyError(MMError, KeyError):
    """Class of Metamath key errors."""
    pass


def vprint(vlevel: int, *arguments: typing.Any) -> None:
    """Print log message if verbosity level is higher than the argument."""
    if verbosity >= vlevel:
        print(*arguments, file=logfile)


class Toks:
    """Class of sets of tokens from which functions read as in an input
    stream.
    """

    def __init__(self, file: io.TextIOWrapper) -> None:
        """Construct a 'Toks' from the given file: initialize a line buffer
        containing the lines of the file, and initialize a set of imported
        files to a singleton containing that file, so as to avoid multiple
        imports.
        """
        self.files_buf = [file]
        self.tokbuf: list[str] = []
        self.imported_files = set({pathlib.Path(file.name).resolve()})

    def read(self) -> StringOption:
        """Read the next token in the token buffer, or if it is empty, split
        the next line into tokens and read from it."""
        while not self.tokbuf:
            if self.files_buf:
                line = self.files_buf[-1].readline()
            else:
                # There is no file to read from: this can only happen if end
                # of file is reached while within a ${ ... $} block.
                raise MMError("Unclosed ${ ... $} block at end of file.")
            if line:  # split the line into a list of tokens
                self.tokbuf = line.split()
                self.tokbuf.reverse()
            else:  # no line: end of current file
                self.files_buf.pop().close()
                if not self.files_buf:
                    return None  # End of database
        tok = self.tokbuf.pop()
        vprint(90, "Token:", tok)
        return tok

    def readf(self) -> StringOption:
        """Read the next token once included files have been expanded.  In the
        latter case, the path/name of the expanded file is added to the set of
        imported files so as to avoid multiple imports.
        """
        tok = self.read()
        while tok == '$[':
            filename = self.read()
            if not filename:
                raise MMError(
                    "Unclosed inclusion statement at end of file.")
            endbracket = self.read()
            if endbracket != '$]':
                raise MMError(
                    ("Inclusion statement for file {} not " +
                     "closed with a '$]'.").format(filename))
            file = pathlib.Path(filename).resolve()
            if file not in self.imported_files:
                # wrap the rest of the line after the inclusion command in a
                # file object
                self.files_buf.append(
                    io.StringIO(
                        " ".join(
                            reversed(
                                self.tokbuf))))
                self.tokbuf = []
                self.files_buf.append(open(file, mode='r', encoding='ascii'))
                self.imported_files.add(file)
                vprint(5, 'Importing file:', filename)
            tok = self.read()
        vprint(80, "Token once included files expanded:", tok)
        return tok

    def readc(self) -> StringOption:
        """Read the next token once included files have been expanded and
        comments have been skipped.
        """
        tok = self.readf()
        while tok == '$(':
            # Note that we use 'read' in this while-loop, and not 'readf',
            # since inclusion statements within a comment are still comments
            # so should be skipped.
            # The following line is not necessary but makes things clearer;
            # note the similarity with the first three lines of 'readf'.
            tok = self.read()
            while tok and tok != '$)':
                if '$(' in tok or '$)' in tok:
                    raise MMError(
                        ("Encountered token '{}' while reading a comment. " +
                         "Comment contents should not contain '$(' nor " +
                         "'$)' as a substring.  In particular, comments " +
                         "should not nest.").format(tok))
                tok = self.read()
            if not tok:
                raise MMError("Unclosed comment at end of file.")
            assert tok == '$)'
            # 'readf' since an inclusion may follow a comment immediately
            tok = self.readf()
        vprint(70, "Token once comments skipped:", tok)
        return tok




class Frame:
    """Class of frames, keeping track of the environment."""

    def __init__(self) -> None:
        """Construct an empty frame."""
        self.v: set[Var] = set()
        self.d: set[Dv] = set()
        self.f: list[Fhyp] = []
        self.f_labels: dict[Var, Label] = {}
        self.e: list[Ehyp] = []
        self.e_labels: dict[tuple[Symbol, ...], Label] = {}
        # Note: both self.e and self.e_labels are needed since the keys of
        # self.e_labels form a set, but the order and repetitions of self.e
        # are needed.


class FrameStack(typing.List[Frame]):
    """Class of frame stacks, which extends lists (considered and used as
    stacks).
    """

    def push(self) -> None:
        """Push an empty frame to the stack."""
        self.append(Frame())

    def add_e(self, stmt: Stmt, label: Label) -> None:
        """Add an essential hypothesis (token tuple) to the frame stack
        top.
        """
        frame = self[-1]
        frame.e.append(stmt)
        frame.e_labels[tuple(stmt)] = label
        # conversion to tuple since dictionary keys must be hashable

    def add_d(self, varlist: typing.List[Var]) -> None:
        """Add a disjoint variable condition (ordered pair of variables) to
        the frame stack top.
        """
        self[-1].d.update((min(x, y), max(x, y))
                          for x, y in itertools.product(varlist, varlist)
                          if x != y)

    def lookup_v(self, tok: Var) -> bool:
        """Return whether the given token is an active variable."""
        return any(tok in fr.v for fr in self)

    def lookup_d(self, x: Var, y: Var) -> bool:
        """Return whether the given ordered pair of tokens belongs to an
        active disjoint variable statement.
        """
        return any((min(x, y), max(x, y)) in fr.d for fr in self)

    def lookup_f(self, var: Var) -> typing.Optional[Label]:
        """Return the label of the active floating hypothesis which types the
        given variable.
        """
        for frame in self:
            try:
                return frame.f_labels[var]
            except KeyError:
                pass
        return None  # Variable is not actively typed

    def lookup_e(self, stmt: Stmt) -> Label:
        """Return the label of the (earliest) active essential hypothesis with
        the given statement.
        """
        stmt_t = tuple(stmt)
        for frame in self:
            try:
                return frame.e_labels[stmt_t]
            except KeyError:
                pass
        raise MMKeyError(stmt_t)

    def find_vars(self, stmt: Stmt) -> typing.Set[Var]:
        """Return the set of variables in the given statement."""
        return {x for x in stmt if self.lookup_v(x)}

    def make_assertion(self, stmt: Stmt) -> Assertion:
        """Return a quadruple (disjoint variable conditions, floating
        hypotheses, essential hypotheses, conclusion) describing the given
        assertion.
        """
        e_hyps = [eh for fr in self for eh in fr.e]
        mand_vars = {tok for hyp in itertools.chain(e_hyps, [stmt])
                     for tok in hyp if self.lookup_v(tok)}
        # print("!!!!!!!!!!!mand_vars:{}".format(mand_vars))
        
        dvs = {(x, y) for fr in self for (x, y)
               in fr.d if x in mand_vars and y in mand_vars}
        f_hyps = []
        for fr in self:
            for typecode, var in fr.f:
                if var in mand_vars:
                    f_hyps.append((typecode, var))
                    mand_vars.remove(var)
                    
        assertion = dvs, f_hyps, e_hyps, stmt
        vprint(18, 'Make assertion:', assertion)
        return assertion


def apply_subst(stmt: Stmt, subst: typing.Dict[Var, Stmt]) -> Stmt:
    """Return the token list resulting from the given substitution
    (dictionary) applied to the given statement (token list).
    """
    result = []
    for tok in stmt:
        if tok in subst:
            result += subst[tok]
        else:
            result.append(tok)
    vprint(20, 'Applying subst', subst, 'to stmt', stmt, ':', result)
    return result


class MM:
    """Class of ("abstract syntax trees" describing) Metamath databases."""

    def __init__(self, begin_label: Label, stop_label: Label) -> None:
        """Construct an empty Metamath database."""
        self.constants: set[Const] = set()
        self.fs = FrameStack()
        self.labels: dict[Label, FullStmt] = {}
        self.begin_label = begin_label
        self.stop_label = stop_label
        self.verify_proofs = not self.begin_label

    def add_c(self, tok: Const) -> None:
        """Add a constant to the database."""
        if tok in self.constants:
            raise MMError(
                'Constant already declared: {}'.format(tok))
        if self.fs.lookup_v(tok):
            raise MMError(
                'Trying to declare as a constant an active variable: {}'.format(tok))
        self.constants.add(tok)

    def add_v(self, tok: Var) -> None:
        """Add a variable to the frame stack top (that is, the current frame)
        of the database.  Allow local variable declarations.
        """
        if self.fs.lookup_v(tok):
            raise MMError('var already declared and active: {}'.format(tok))
        if tok in self.constants:
            raise MMError(
                'var already declared as constant: {}'.format(tok))
        self.fs[-1].v.add(tok)

    def add_f(self, typecode: Const, var: Var, label: Label) -> None:
        """Add a floating hypothesis (ordered pair (variable, typecode)) to
        the frame stack top (that is, the current frame) of the database.
        """
        if not self.fs.lookup_v(var):
            raise MMError('var in $f not declared: {}'.format(var))
        if typecode not in self.constants:
            raise MMError('typecode in $f not declared: {}'.format(typecode))
        if any(var in fr.f_labels for fr in self.fs):
            raise MMError(
                ("var in $f already typed by an active " +
                 "$f-statement: {}").format(var))
        frame = self.fs[-1]
        frame.f.append((typecode, var))
        frame.f_labels[var] = label

    def readstmt_aux(
            self,
            stmttype: Stmttype,
            toks: Toks,
            end_token: str) -> Stmt:
        """Read tokens from the input (assumed to be at the beginning of a
        statement) and return the list of tokens until the end_token
        (typically "$=" or "$.").
        """
        stmt = []
        tok = toks.readc()
        while tok and tok != end_token:
            is_active_var = self.fs.lookup_v(tok)
            if stmttype in {'$d', '$e', '$a', '$p'} and not (
                    tok in self.constants or is_active_var):
                raise MMError(
                    "Token {} is not an active symbol".format(tok))
            if stmttype in {
                '$e',
                '$a',
                    '$p'} and is_active_var and not self.fs.lookup_f(tok):
                raise MMError(("Variable {} in {}-statement is not typed " +
                               "by an active $f-statement).").format(tok, stmttype))
            stmt.append(tok)
            tok = toks.readc()
        if not tok:
            raise MMError(
                "Unclosed {}-statement at end of file.".format(stmttype))
        assert tok == end_token
        vprint(20, 'Statement:', stmt)
        return stmt

    def read_non_p_stmt(self, stmttype: Stmttype, toks: Toks) -> Stmt:
        """Read tokens from the input (assumed to be at the beginning of a
        non-$p-statement) and return the list of tokens until the next
        end-statement token '$.'.
        """
        return self.readstmt_aux(stmttype, toks, end_token="$.")

    def read_p_stmt(self, toks: Toks) -> typing.Tuple[Stmt, Stmt]:
        """Read tokens from the input (assumed to be at the beginning of a
        p-statement) and return the couple of lists of tokens (stmt, proof)
        appearing in "$p stmt $= proof $.".
        """
        stmt = self.readstmt_aux("$p", toks, end_token="$=")
        proof = self.readstmt_aux("$=", toks, end_token="$.")
        return stmt, proof

    def read(self, toks: Toks) -> None:
        """Read the given token list to update the database and verify its
        proofs.
        """
        self.fs.push()
        label = None
        tok = toks.readc()
        while tok and tok != '$}':
            if tok == '$c':
                for tok in self.read_non_p_stmt(tok, toks):
                    self.add_c(tok)
            elif tok == '$v':
                for tok in self.read_non_p_stmt(tok, toks):
                    self.add_v(tok)
            elif tok == '$f':
                stmt = self.read_non_p_stmt(tok, toks)
                if not label:
                    raise MMError(
                        '$f must have label (statement: {})'.format(stmt))
                if len(stmt) != 2:
                    raise MMError(
                        '$f must have length two but is {}'.format(stmt))
                self.add_f(stmt[0], stmt[1], label)
                self.labels[label] = ('$f', [stmt[0], stmt[1]])
                label = None
            elif tok == '$e':
                if not label:
                    raise MMError('$e must have label')
                stmt = self.read_non_p_stmt(tok, toks)
                self.fs.add_e(stmt, label)
                self.labels[label] = ('$e', stmt)
                label = None
            elif tok == '$a':
                if not label:
                    raise MMError('$a must have label')
                self.labels[label] = (
                    '$a', self.fs.make_assertion(
                        self.read_non_p_stmt(tok, toks)))
                label = None
            elif tok == '$p':
                if not label:
                    raise MMError('$p must have label')
                stmt, proof = self.read_p_stmt(toks)
                #print("!!!stmt:{}".format(stmt))
                dvs, f_hyps, e_hyps, conclusion = self.fs.make_assertion(stmt)
                if self.verify_proofs:
                    vprint(2, 'Verify:', label)
                    #print("self.labels:{}".format(self.labels))
                    self.verify(f_hyps, e_hyps, conclusion, proof)
                
                #print("label:{}".format(label))
                self.labels[label] = ('$p', (dvs, f_hyps, e_hyps, conclusion))
                label = None
            elif tok == '$d':
                self.fs.add_d(self.read_non_p_stmt(tok, toks))
            elif tok == '${':
                self.read(toks)
            elif tok == '$)':
                raise MMError("Unexpected '$)' while not within a comment")
            elif tok[0] != '$':
                if tok in self.labels:
                    raise MMError("Label {} multiply defined.".format(tok))
                label = tok
                vprint(20, 'Label:', label)
                if label == self.stop_label:
                    # TODO: exit gracefully the nested calls to self.read()
                    sys.exit(0)
                if label == self.begin_label:
                    self.verify_proofs = True
            else:
                raise MMError("Unknown token: '{}'.".format(tok))
            tok = toks.readc()
        self.fs.pop()

    def treat_step(self,
                   step: FullStmt,
                   stack: typing.List[Stmt]) -> None:
        """
           Carry out the given proof step (given the label to treat and the
           current proof stack).  This modifies the given stack in place.
           
        """
        vprint(10, 'Proof step:', step)
        steptype, stepdata = step
        if steptype in ('$e', '$f'):
            # e, f变量进入堆栈
            #print("=====stepdata1:{}".format(stepdata))
            stack.append(stepdata)
            #print("===stack1:{}".format(stack))
        elif steptype in ('$a', '$p'):
            # print("===steptype2:{}".format(steptype))
            # print("===stack2:{}".format(stack))
            
            dvs0, f_hyps0, e_hyps0, conclusion0 = stepdata
            
            # print("dvs0:{}".format(dvs0))
            # print("f_hyps0:{}".format(f_hyps0))
            # print("e_hyps0:{}".format(e_hyps0))
            # print("conclusion0:{}".format(conclusion0))
            
            npop = len(f_hyps0) + len(e_hyps0)
            sp = len(stack) - npop
            if sp < 0:
                raise MMError(
                    ("Stack underflow: proof step {} requires too many " +
                     "({}) hypotheses.").format(
                        step,
                        npop))
            subst: dict[Var, Stmt] = {}
            for typecode, var in f_hyps0:
                # f是这里的待替换的变量
                entry = stack[sp]
                # print("var:{}".format(var))
                # print("===entry1:{}".format(entry))
                
                if entry[0] != typecode:
                    raise MMError(
                        ("Proof stack entry {} does not match floating " +
                         "hypothesis ({}, {}).").format(entry, typecode, var))
                subst[var] = entry[1:]
                sp += 1
                
            vprint(15, 'Substitution to apply:', subst)
            #print("subst:{}".format(subst))
            for h in e_hyps0:
                entry = stack[sp]
                
                #print("h:{}".format(h))
                subst_h = apply_subst(h, subst)
                # print("subst_h:{}".format(subst_h))
                # print("entry2:{}".format(entry))
                
                if entry != subst_h:
                    raise MMError(("Proof stack entry {} does not match " +
                                   "essential hypothesis {}.")
                                  .format(entry, subst_h))
                sp += 1
                
                
            for x, y in dvs0:
                vprint(16, 'dist', x, y, subst[x], subst[y])
                x_vars = self.fs.find_vars(subst[x])
                y_vars = self.fs.find_vars(subst[y])
                vprint(16, 'V(x) =', x_vars)
                vprint(16, 'V(y) =', y_vars)
                for x0, y0 in itertools.product(x_vars, y_vars):
                    if x0 == y0 or not self.fs.lookup_d(x0, y0):
                        raise MMError("Disjoint variable violation: " +
                                      "{} , {}".format(x0, y0))
            #print("before del stack:{}".format(stack))
            del stack[len(stack) - npop:]
            # print("after del stack:{}".format(stack))
            # print("apply_subst(conclusion0, subst):{}".format(apply_subst(conclusion0, subst)))
            stack.append(apply_subst(conclusion0, subst))
            
        vprint(12, 'Proof stack:', stack)

    def treat_normal_proof(self, proof: typing.List[str]) -> typing.List[Stmt]:
        """Return the proof stack once the given normal proof has been
        processed.
        """
        stack: list[Stmt] = []
        for label in proof:
            self.treat_step(self.labels[label], stack)
        return stack

    def treat_compressed_proof(
            self,
            f_hyps: typing.List[Fhyp],
            e_hyps: typing.List[Ehyp],
            proof: typing.List[str]) -> typing.List[Stmt]:
        """Return the proof stack once the given compressed proof for an
        assertion with the given $f and $e-hypotheses has been processed.
        """
        # Preprocessing and building the lists of proof_ints and labels
        flabels = [self.fs.lookup_f(v) for _, v in f_hyps]
        elabels = [self.fs.lookup_e(s) for s in e_hyps]
        plabels = flabels + elabels  # labels of implicit hypotheses
        idx_bloc = proof.index(')')  # index of end of label bloc
        plabels += proof[1:idx_bloc]  # labels which will be referenced later
        
        #print("===plabels:{}".format(plabels))
        compressed_proof = ''.join(proof[idx_bloc + 1:])
        vprint(5, 'Referenced labels:', plabels)
        label_end = len(plabels)
        vprint(5, 'Number of referenced labels:', label_end)
        vprint(5, 'Compressed proof steps:', compressed_proof)
        vprint(5, 'Number of steps:', len(compressed_proof))
        proof_ints = []  # integers referencing the labels in 'labels'
        cur_int = 0  # counter for radix conversion
        
        for ch in compressed_proof:
            if ch == 'Z':
                proof_ints.append(-1)
            elif 'A' <= ch <= 'T':
                proof_ints.append(20 * cur_int + ord(ch) - 65)  # ord('A') = 65
                cur_int = 0
            else:  # 'U' <= ch <= 'Y'
                cur_int = 5 * cur_int + ord(ch) - 84  # ord('U') = 85
        vprint(5, 'Integer-coded steps:', proof_ints)
        # Processing of the proof
        stack: list[Stmt] = []  # proof stack
        # print("stack of start:{}".format(stack))
        
        # statements saved for later reuse (marked with a 'Z')
        saved_stmts = []
        # can be recovered as len(saved_stmts) but less efficient
        n_saved_stmts = 0
        
        #print("start compressed_proof:{}".format(compressed_proof))
        # 连续进行一系列的变量代换
        for proof_int in proof_ints:
            #print("proof_int:{}".format(proof_int))
            if proof_int == -1:  # save the current step for later reuse
                stmt = stack[-1]
                vprint(15, 'Saving step', stmt)
                saved_stmts.append(stmt)
                n_saved_stmts += 1
            elif proof_int < label_end:
                # proof_int denotes an implicit hypothesis or a label in the
                # label bloc
                #('$p', (dvs, f_hyps, e_hyps, conclusion))
                
                # print("self.labels[plabels[proof_int]]:{}".format(self.labels[plabels[proof_int]]))
                # print("plabels[proof_int]:{}".format(plabels[proof_int]))
                
                self.treat_step(self.labels[plabels[proof_int]], stack)
                
            elif proof_int >= label_end + n_saved_stmts:
                MMError(
                    "Not enough saved proof steps ({} saved but calling " +
                    "the {}th).".format(
                        n_saved_stmts,
                        proof_int))
            else:  # label_end <= proof_int < label_end + n_saved_stmts
                # proof_int denotes an earlier proof step marked with a 'Z'
                # A proof step that has already been proved can be treated as
                # a dv-free and hypothesis-free axiom.
                stmt = saved_stmts[proof_int - label_end]
                vprint(15, 'Reusing step', stmt)
                self.treat_step(
                    ('$a',
                     (set(), [], [], stmt)),
                    stack)
                
            # print("end of stack:{}".format(stack))
            
        return stack

    def verify(
            self,
            f_hyps: typing.List[Fhyp],
            e_hyps: typing.List[Ehyp],
            conclusion: Stmt,
            proof: typing.List[str]) -> None:
        """Verify that the given proof (in normal or compressed format) is a
        correct proof of the given assertion.
        """
        # It would not be useful to also pass the list of dv conditions of the
        # assertion as an argument since other dv conditions corresponding to
        # dummy variables should be 'lookup_d'ed anyway.
        
        if proof[0] == '(':  # compressed format
            stack = self.treat_compressed_proof(f_hyps, e_hyps, proof)
        else:  # normal format
            stack = self.treat_normal_proof(proof)
        vprint(10, 'Stack at end of proof:', stack)
        if not stack:
            raise MMError(
                "Empty stack at end of proof.")
        if len(stack) > 1:
            raise MMError(
                "Stack has more than one entry at end of proof (top " +
                "entry: {} ; proved assertion: {}).".format(
                    stack[0],
                    conclusion))
        if stack[0] != conclusion:
            raise MMError(("Stack entry {} does not match proved " +
                          " assertion {}.").format(stack[0], conclusion))
        vprint(3, 'Correct proof!')

    def dump(self) -> None:
        """Print the labels of the database."""
        print(self.labels)


def parse_tactic(tactic):
    """Parse tactic string. For example, if the tactic is
        [[ |- ph |- ( ph -> ps ) ]] |- ps {{ ph : ps }} {{ ps : ch }} 
    then 
        premise = '|- ph |- ( ph -> ps )'
        conclusion = '|- ps'
        substitution = '{{ ph : ps }} {{ ps : ch }}'
    """
    tactic_pattern = r"\[\[ (\|- ((?! \]\]).)*)* \]\] (((?! \{\{).)*)(.*)"
    tactic = tactic.strip()
    match = re.match(tactic_pattern, tactic)
    if match:
        premises = match.group(1)
        conclusion = match.group(3)
        substitution = match.group(5).strip()
        if premises is None:
            premises = ''
        return premises, conclusion, substitution
    else:
        raise ValueError("Syntax error for tactic: {}".format(tactic))


def parse_tactic_state(tactic_state):
    """Similar to `parse_tactic`, only applied to the tactic state part."""
    ts_pattern = r"\[\[ (\|- ((?! \]\]).)*)* \]\] (.*)"
    match = re.match(ts_pattern, tactic_state)
    if match:
        premises = match.group(1)
        conclusion = match.group(3)
        if premises is None:
            premises = ''
        return premises, conclusion
    else:
        raise ValueError("Syntax error for tactic state: {}".format(tactic_state))


def parse_premises(premises):
    """Parse a string of premises. 
    
    For example, if 
        premises = '|- ( ph -> ps ) |- ( ps -> ch )'
    then return
        li_premises = ['|- ( ph -> ps )', '|- ( ps -> ch )']
    """
    premise_pattern = r"(\|- ((?! \|- ).)*)"
    res = re.findall(premise_pattern, premises)
    li_premises = [x for x, _ in res]
    return li_premises


def parse_substitution(subst):
    """Parse a string of substitution. 
    
    For example, if 
        subst = '{{ ph : ps }} {{ ps : ch : ps }}'
    then return
        dict_subst = {'ph': 'ps', 'ps': 'ch : ps'}
    """
    sub_pattern = r"\{\{ (\S*) : (((?! \}\}).)*) \}\}"
    res = re.findall(sub_pattern, subst)
    dict_subst = {k : v for k, v, _ in res}
    return dict_subst


def make_goal(premises, conclusion):
    return "[[ " + premises + " ]] " + conclusion


class MetaFatalError(Exception):
    """Raise when Lean fatal error ocurred"""
    pass

class MMServer():
    """Class of ("abstract syntax trees" describing) Metamath databases."""
    
    def __init__(self, begin_label, stop_label, db_file, normalize_tab = True) -> None:
        self.mm = MM(begin_label, stop_label)
        
        vprint(100, "db_file:{}".format(db_file))
        self.mm.read(Toks(db_file))
        self.labels = self.mm.labels
        self.search_count = 0
        
        self.search_id2tactic_state_count = dict()
        self.search_id2tactic_state_list = dict()
        self.search_id2global_premise = dict()
        self.search_id2global_goal = dict()
        self.search_id2proof_steps = dict()
        self.search_id2local_conclusion = dict()
        # Goals to prove later. This corresponds to the usage of 'Z' in
        # compressed proofs.
        self.search_id2saved_goals = dict()
        
        self.search_id2f_hyps = dict()
        self.search_id2e_hyps = dict()

        self.search_id2var_type = dict()
        
        # self.search_id2p_hyps = dict()
        # self.search_id2a_hyps = dict()
        
        self.is_alive = True
        self.normalize_tab = normalize_tab
        
        self.axiom_token_set = list()#set()
     
        self.axiom_and_proven_token_set = set()
        self.get_axiom_and_proven_to_decl_name()
            
    def get_labels(self, dec_name, search_id):
        """
            Get the all label before the dec_name.
        """
        label = dict()
        for key, value in zip(self.labels.keys(), self.labels.values()):
            if dec_name == key:
                break
            label[key] = value
            
        return label 
    
    def get_axiom2decl_name(self):
        for key, value in zip(self.labels.keys(), self.labels.values()):                
            if value[0] == "$a":
                         
               premises = value[1][-2]
               conclusion = value[1][-1]     
               premise_list = []
               
               for premise in premises:
                   premise_str = " ".join(premise)
                   premise_list.append(premise_str)
               
               conclusion_str = " ".join(conclusion)    
               axiom_str = "[[ " + " ".join(premise_list) + " ]] " + conclusion_str   
               self.axiom_token_set.append(axiom_str)
    
    def get_f_e(self, labels, search_id):
        
        for key, value in zip(labels.keys(), labels.values()):
            type_str = str(value[0])
            if type_str == "$f":
               value_str = " ".join(value[1])
               self.search_id2f_hyps[search_id].add(value_str)
               #print("value:{}".format(value))
            elif type_str == "$e":
               value_str = " ".join(value[1])
               self.search_id2e_hyps[search_id].add(value_str)
               #print("value:{}".format(value))

                            
    def init_search(self, dec_name, namespaces=""):
        """
           {'error': 'not_a_theorem: name=INT_1_cdwv open_ns=data.real.basic', 'proof_steps': [], 'search_id': None, 'tactic_state': None, 'tactic_state_id': None}
        """
        error  = None
        labels = self.get_labels(dec_name, self.search_count) #self.labels[dec_name][1]
        
        try:
            label = self.labels[dec_name][1]
            #print("label:{}".format(label))
        except:
            raise MMError("Not a theorem: {}".format(dec_name))
        
        e = label[2]
        conclusion = label[3]

        conclusion_str = ""
        conclusion_len = len(conclusion)
        
        for i, token in enumerate(conclusion):
            conclusion_str += token
            if i!= (conclusion_len-1):
               conclusion_str += " "
        
        all_str = ""
        for List in e:
            for token in List:
                all_str += str(token) + " "
        
        result = dict()
        e_global = "[[ " + all_str +  " ]]"    
        tactic_state = e_global + " " + conclusion_str
        
        if error == None:
            result['tactic_state'] = tactic_state
            result['proof_steps'] = [] 
            result['search_id'] = self.search_count
            
            self.search_id2tactic_state_count[self.search_count] = 0
            result['tactic_state_id'] = self.search_id2tactic_state_count[self.search_count] #self.search_count
            result['error'] =None
            
            global_premise, goal = parse_tactic_state(tactic_state)

            self.search_id2global_premise[self.search_count] = global_premise
            self.search_id2tactic_state_list[self.search_count] = [tactic_state]
            self.search_id2f_hyps[self.search_count] = set()
            self.search_id2e_hyps[self.search_count] = set()
            self.search_id2var_type[self.search_count] = dict()
            self.search_id2proof_steps[self.search_count] = []
            self.search_id2global_goal[self.search_count] = [goal]
            self.search_id2local_conclusion[self.search_count] = []
            
            self.get_f_e(labels, self.search_count)

            assert len(self.search_id2f_hyps[self.search_count])>0
            assert len(self.search_id2e_hyps[self.search_count])>0

            for f in self.search_id2f_hyps[self.search_count]:
                tc, var = f.split(' ')
                self.search_id2var_type[self.search_count][var] = tc
            
            self.search_id2tactic_state_count[self.search_count]  += 1
            self.search_count += 1
        else:
            result['tactic_state'] = None
            result['proof_steps'] = [] 
            result['search_id'] = None
            result['tactic_state_id'] = None
            result['error'] = error
        
        return result
    
    def get_axiom_and_proven_to_decl_name(self):
        for key, value in zip(self.labels.keys(), self.labels.values()):                
            if value[0] == "$a" or value[0] == "$p":
                premises = value[1][-2]
                conclusion = value[1][-1]     
                
                premise_list = []
                for premise in premises:
                    premise_str = " ".join(premise)
                    premise_list.append(premise_str)
                
                conclusion_str = " ".join(conclusion) 
                axiom_str = "[[ " + " ".join(premise_list) + " ]] " + conclusion_str
                self.axiom_and_proven_token_set.add(axiom_str)

    def substitute(self, subst, conclusion):
        temp_conclusion = ""
        token_list = conclusion.strip().split(" ")
        list_len = len(token_list) 
        
        for i, key in enumerate(token_list):
            if key == "":
                continue
            if i < (list_len - 1):
                if key in subst.keys():
                    temp_conclusion += subst[key]+" "
                else:
                    temp_conclusion += key+" "
            else:
                if key in subst.keys():
                    temp_conclusion += subst[key]
                else:
                    temp_conclusion += key
                   
        return temp_conclusion
    
    def check_f(self, f_list, search_id):        
        """Add $f statement if not already proven in the global scope.

        Args:
            f_list (_type_):  bound variables
            search_id (_type_): 

        Raises:
            MMError: _description_
        """
        new_goal_list = []
        vprint(100, "self.search_id2f_hyps[search_id]: {}".format( self.search_id2f_hyps[search_id]))
        for f in f_list:
            if (f not in self.search_id2e_hyps[search_id]) and (f not in self.search_id2f_hyps[search_id]):
                new_goal_list.append(f)
        
        return new_goal_list
    
    def already_true(self, premise_list, global_premise, substitute, search_id):
        """
            premise_list   :     Some Premises of Current Proof.
            all_f_to_check :     Some f to be checked in the global scope
        """
        
        for pre in premise_list:

            if pre == '':
               continue
           
            sub_pre = self.substitute(substitute, pre)
            if sub_pre not in global_premise:
               vprint(100, "Add sub_pre:", sub_pre)
               self.search_id2global_goal[search_id].append(sub_pre)
            else: # TODELETE
                vprint(100, "sub_pre={} already in global_premise={}".format(sub_pre, global_premise))
        
    def check_conclusion(self, substitute, conclusion, tactic_state, search_id):
        """
           delete all the goal
        """
        sub_conclusion = self.substitute(substitute, conclusion)
        goal = tactic_state.split("]] ")[1]

        goal_concl = goal.strip()
        sub_concl = sub_conclusion.strip()
        
        if goal_concl != sub_concl:
            raise ValueError("Inconsistent conclusion: expected\n\t" +\
                "{}\nbut got\n\t{}\n".format(goal_concl, sub_concl) +\
                "using substitution\n\t{}\n".format(substitute) +\
                "from tactic state\n\t{}".format(tactic_state))
        
        if search_id in self.search_id2saved_goals and\
            sub_conclusion not in self.search_id2saved_goals[search_id]:
            self.search_id2local_conclusion[search_id].append(sub_conclusion)
        
    def check_axiom_and_proven(self, tactic):
            
        decl_name = tactic.split(" {{")[0]
        if (decl_name not in self.axiom_and_proven_token_set): #and (decl_name not in ):
           raise MMError("{} is not in existing axioms or theorems.".format(decl_name))
    
    def check_syntax(self, tactic):
        
        pattern = "\[\[ .* \]\] .*( \{\{ .* \}\})*"
        match_str = re.search(pattern, tactic, flags=0).group()
        if match_str == None:
            raise MMError("tactic syntax error.")
        
        return match_str
    
    def clear_search(self, search_id):
        del self.search_id2tactic_state_count[search_id]
        del self.search_id2global_premise[search_id] 
        del self.search_id2tactic_state_list[search_id] 
        del self.search_id2f_hyps[search_id] 
        del self.search_id2e_hyps[search_id] 
        del self.search_id2var_type[search_id]
        del self.search_id2proof_steps[search_id] 
        del self.search_id2global_goal[search_id] 
        del self.search_id2local_conclusion[search_id] 
        
    def split_goals(self, tactic_state, search_id):
        tactic_state_list = tactic_state.split("\n")
        if "goals" in tactic_state_list[0]:
            tactic_state_list = tactic_state_list[1:]
            
        return tactic_state_list[0]
    
    def generate_goals(self, global_premise, search_id):

        global_premise = global_premise.strip()
        
        goal_str = ""
        if len(self.search_id2global_goal[search_id])>1:
           goal_number = len(self.search_id2global_goal[search_id])
           goal_str = str(goal_number) + " goals\n"
        
            # IMPORTANT: reverse the order of the goals due to backward reasoning
           for i, goal in enumerate(self.search_id2global_goal[search_id][::-1]):
               if  i <  (goal_number-1):
                   goal_str +=  "[[ " + global_premise + " ]]" + " " + goal + "\n"
               else:
                   goal_str +=  "[[ " + global_premise + " ]]" + " " + goal
        else:
            goal_str = "[[ " + global_premise + " ]]" + " " + self.search_id2global_goal[search_id][0]
           
        return goal_str
    
    def delete_conclusion(self, search_id):
        """Remove the conclusion just proven."""
        self.search_id2global_goal[search_id].pop()
        
    def verify(self, tactic_state, tactic, search_id):
        # Get the first goal
        tactic_state = self.split_goals(tactic_state, search_id)
        
        # Check if the tactic is syntaxically correct and parse the premise 
        # and conclusion. 
        premise, conclusion, subst = parse_tactic(tactic)

        # Make the goal [[ <PREMISES> ]] <CONCLUSION> for convenience
        tactic_goal = make_goal(premise, conclusion)

        # Get the current conclusion to prove
        conclusion_to_prove = self.search_id2global_goal[search_id][-1]

        vprint(100, "self.axiom_and_proven_token_set:", self.axiom_and_proven_token_set)
        
        # This is the case when the goal is proven 
        # more than once in the forward proof. This corresponds to the usage 
        # of 'Z' in compressed proofs.
        if conclusion == conclusion_to_prove and\
           not tactic_goal in self.axiom_and_proven_token_set:
            if search_id in self.search_id2saved_goals:
                self.search_id2saved_goals[search_id].add(conclusion)
            else:
                self.search_id2saved_goals[search_id] = {conclusion}
        else:
            self.check_axiom_and_proven(tactic_goal)

            # Remove conclusion in saved goals
            if search_id in self.search_id2saved_goals and\
            conclusion_to_prove in self.search_id2saved_goals[search_id]:
                self.search_id2saved_goals[search_id].remove(conclusion_to_prove)
                vprint(100, "Finally proved {} after some procrastination!".format(conclusion_to_prove))
        
        if search_id in self.search_id2saved_goals:
            vprint(100, "self.search_id2saved_goals[search_id]: {}"\
                .format(self.search_id2saved_goals[search_id]))
        
        # Generate $f statements to prove
        substitute = parse_substitution(subst)
        all_f_to_check = []
        for var in substitute:
            expr = substitute[var]
            typecode = self.search_id2var_type[search_id][var]
            check_value = typecode + " " + expr
            all_f_to_check.append(check_value)
        vprint(100, "all_f_to_check: ", all_f_to_check)


        # 在这里检查结论
        self.check_conclusion(substitute, conclusion, tactic_state, search_id)
        
        premise_list = parse_premises(premise)
        global_premise = self.search_id2global_premise[search_id]

        self.delete_conclusion(search_id)
        
        # New $f statements to add
        new_goal_list = self.check_f(all_f_to_check, search_id)
        # Add $f
        self.search_id2global_goal[search_id] = self.search_id2global_goal[search_id] + new_goal_list
        # Add $e
        self.already_true(premise_list, global_premise, substitute, search_id)
        
        # Abandon saving proof steps to avoid occupying too much space
        # self.search_id2proof_steps[search_id].append(tactic)
        
        # Return resulting state
        if len((self.search_id2global_goal[search_id]))>0:
             state_goal = self.generate_goals(global_premise, search_id)
             vprint(100, "Before return:", self.search_id2global_goal[search_id])
             vprint(100, "state_goal:", state_goal)
             return state_goal
        else:
             if search_id in self.search_id2saved_goals:
                assert len(self.search_id2saved_goals[search_id]) == 0
             return "no goals"
               
    def __output_parse(self, input):
        if len(input) <= 0:
            raise MetaFatalError
        
        if input['search_id'] is not None:
            search_id = int(input['search_id'])
            
        if input['tactic_state_id'] is not None:
            tactic_state_id  = int(input['tactic_state_id'])
            
        tactic_state = self.search_id2tactic_state_list[search_id][tactic_state_id] 
                
        tactic = input["tactic"]
            
        if self.normalize_tab:
            if tactic_state is not None:
               tactic_state = tactic_state.replace('\t', ' ')
        
        state_goal = self.verify(tactic_state, tactic, search_id)
        self.search_id2tactic_state_list[search_id].append(state_goal)
        
        output_dict = dict()
        output_dict["tactic_state"] = state_goal
        output_dict["search_id"] = search_id
        output_dict["tactic_state_id"] = tactic_state_id + 1
        output_dict["error"] = None
        output_dict["proof_steps"] = self.search_id2proof_steps[search_id]
        
        #print("output_dict:{}".format(output_dict))
        return output_dict

    def __run(self, inputs_state):
        if not self.is_alive:
            return {'error':'proc_killed','search_id':None, 'tactic_state':None, 'tactic_state_id':None}
        
        inputs_state["proof_steps"] = self.search_id2proof_steps[inputs_state["search_id"]]
        try:
            result = self.__output_parse(inputs_state)
            return result
        except Exception as meta_e:
            # print("meta_e:", meta_e)
            # print("inputs_state:", inputs_state)
            inputs_state["error"] =  str(meta_e)
            return inputs_state

    def run_tac(self, search_id, tactic_id, tactic):
        import re
        tactic = "".join(re.findall("[^\n\t\a\b\r]+",tactic))
        inputs = dict()
        inputs["search_id"] = search_id
        inputs["tactic_state_id"] = tactic_id
        inputs["tactic"] = tactic
        
        return self.__run(inputs)
    
    def kill(self):
        self.is_alive = False
        
        
if __name__ == '__main__':
    """Parse the arguments and verify the given Metamath database."""
    parser = argparse.ArgumentParser(description="""Verify a Metamath database.
      The grammar of the whole file is verified.  Proofs are verified between
      the statements with labels BEGIN_LABEL (included) and STOP_LABEL (not
      included).

      One can also use bash redirections:
         '$ python3 mmverify.py < file.mm 2> file.log'
      in place of
         '$ python3 mmverify.py file.mm --logfile file.log'
      but this fails in case 'file.mm' contains (directly or not) a recursive
      inclusion statement '$[ file.mm $]'.""")
    parser.add_argument(
        'database',
        nargs='?',
        type=argparse.FileType(
            mode='r',
            encoding='ascii'),
        default=sys.stdin,
        help="""database (Metamath file) to verify, expressed using relative
          path (defaults to <stdin>)""")
    
    parser.add_argument(
        '-l',
        '--logfile',
        dest='logfile',
        type=argparse.FileType(
            mode='w',
            encoding='ascii'),
        default=sys.stderr,
        help="""file to output logs, expressed using relative path (defaults to
          <stderr>)""")

    parser.add_argument(
        '-b',
        '--begin-label',
        dest='begin_label',
        type=str,
        help="""label where to begin verifying proofs (included, if it is a
          provable statement)""")
    parser.add_argument(
        '-s',
        '--stop-label',
        dest='stop_label',
        type=str,
        help='label where to stop verifying proofs (not included)')
    args = parser.parse_args()
    verbosity = args.verbosity
    db_file = args.database
    logfile = args.logfile
    vprint(1, 'mmverify.py -- Proof verifier for the Metamath language')
    mm = MMServer(args.begin_label, args.stop_label, db_file)
    
    vprint(1, 'Reading source file "{}"...'.format(db_file.name))

    mm.read(Toks(db_file))
    vprint(1, 'No errors were found.')
    # mm.dump()
