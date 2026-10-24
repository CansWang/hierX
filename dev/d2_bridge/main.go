// hx-d2-bridge exposes upstream compilation without layout or Hx interpretation.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/d2lang/d2/d2compiler"
	"github.com/d2lang/d2/d2graph"
	"github.com/d2lang/d2/d2parser"
)

const protocol = "hx-d2-bridge/1"
const upstream = "v0.9.0"
const revision = "d5a51743b6d5c00f1ec6f8340003f5d5a6ba4eda"

type snapshot struct {
	data []byte
	info fs.FileInfo
}
type sourceFS struct {
	root  string
	files map[string]snapshot
}
type memoryFile struct {
	*bytes.Reader
	info fs.FileInfo
}

func (f *memoryFile) Stat() (fs.FileInfo, error) { return f.info, nil }
func (f *memoryFile) Close() error               { return nil }
func (s *sourceFS) Open(name string) (fs.File, error) {
	if !fs.ValidPath(name) {
		return nil, fmt.Errorf("invalid import path %q", name)
	}
	if saved, ok := s.files[name]; ok {
		return &memoryFile{bytes.NewReader(saved.data), saved.info}, nil
	}
	full, err := filepath.EvalSymlinks(filepath.Join(s.root, filepath.FromSlash(name)))
	if err != nil {
		return nil, err
	}
	rel, err := filepath.Rel(s.root, full)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return nil, fmt.Errorf("import %q escapes project root", name)
	}
	f, err := os.Open(full)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, fmt.Errorf("import %q is not a regular file", name)
	}
	data, err := io.ReadAll(f)
	if err != nil {
		return nil, err
	}
	s.files[name] = snapshot{data, info}
	return &memoryFile{bytes.NewReader(data), info}, nil
}

type location struct {
	File      string `json:"file"`
	Line      int    `json:"line"`
	Column    int    `json:"column"`
	EndLine   int    `json:"end_line"`
	EndColumn int    `json:"end_column"`
}
type object struct {
	ID           string     `json:"id"`
	Path         []string   `json:"path"`
	Parent       string     `json:"parent"`
	Label        string     `json:"label"`
	Classes      []string   `json:"classes"`
	Link         string     `json:"link"`
	Sources      []location `json:"sources"`
	Presentation bool       `json:"presentation"`
}
type edge struct {
	ID           string     `json:"id"`
	Source       string     `json:"source"`
	Target       string     `json:"target"`
	Forward      bool       `json:"forward"`
	Label        string     `json:"label"`
	Classes      []string   `json:"classes"`
	Sources      []location `json:"sources"`
	Presentation bool       `json:"presentation"`
}
type diagnostic struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	File    string `json:"file,omitempty"`
	Line    int    `json:"line,omitempty"`
	Column  int    `json:"column,omitempty"`
}
type input struct {
	File   string `json:"file"`
	SHA256 string `json:"sha256"`
}
type result struct {
	Protocol     string       `json:"protocol"`
	D2           string       `json:"d2_version"`
	Revision     string       `json:"d2_commit"`
	OK           bool         `json:"ok"`
	Objects      []object     `json:"objects"`
	Edges        []edge       `json:"edges"`
	Inputs       []input      `json:"inputs"`
	Diagnostics  []diagnostic `json:"diagnostics"`
	Boards       bool         `json:"boards"`
	Presentation bool         `json:"presentation"`
}

func path(o *d2graph.Object) []string {
	if o == nil || o.Parent == nil {
		return nil
	}
	return append(path(o.Parent), o.IDVal)
}
func compile(root, entry string) result {
	out := result{Protocol: protocol, D2: upstream, Revision: revision,
		Objects: []object{}, Edges: []edge{}, Inputs: []input{}, Diagnostics: []diagnostic{}}
	s := &sourceFS{root: root, files: make(map[string]snapshot)}
	r, err := s.Open(entry)
	if err == nil {
		var g *d2graph.Graph
		g, config, compileErr := d2compiler.Compile(entry, r, &d2compiler.CompileOptions{FS: s})
		err = compileErr
		r.Close()
		if err == nil {
			out.Presentation = config != nil || g.Root.Direction.Value != "" || g.Root.Style != (d2graph.Style{})
			out.Boards = len(g.Layers)+len(g.Scenarios)+len(g.Steps) > 0
			for _, o := range g.Objects {
				x := object{ID: o.AbsID(), Path: path(o), Label: o.Label.Value,
					Classes: o.Classes, Sources: []location{}}
				if o.Parent != nil {
					x.Parent = o.Parent.AbsID()
				}
				if o.Link != nil {
					x.Link = o.Link.Value
				}
				x.Presentation = o.Style != (d2graph.Style{}) || o.Shape.Value != "rectangle" || o.WidthAttr != nil || o.HeightAttr != nil
				x.Presentation = x.Presentation || o.Direction.Value != "" || o.Top != nil || o.Left != nil || o.GridRows != nil || o.GridColumns != nil
				for _, ref := range o.References {
					if ref.Key != nil {
						p := ref.Key.Range
						x.Sources = append(x.Sources, location{p.Path, p.Start.Line + 1, p.Start.Column + 1, p.End.Line + 1, p.End.Column + 1})
					}
				}
				out.Objects = append(out.Objects, x)
			}
			for _, e := range g.Edges {
				x := edge{ID: fmt.Sprintf("(%s -> %s)[%d]", e.Src.AbsID(), e.Dst.AbsID(), e.Index),
					Source: e.Src.AbsID(), Target: e.Dst.AbsID(), Forward: !e.SrcArrow && e.DstArrow,
					Label: e.Label.Value, Classes: e.Classes, Sources: []location{}}
				x.Presentation = e.Style != (d2graph.Style{}) || e.SrcArrowhead != nil || e.DstArrowhead != nil
				for _, ref := range e.References {
					if ref.Edge != nil {
						p := ref.Edge.Range
						x.Sources = append(x.Sources, location{p.Path, p.Start.Line + 1, p.Start.Column + 1, p.End.Line + 1, p.End.Column + 1})
					}
				}
				out.Edges = append(out.Edges, x)
			}
		}
	}
	if err != nil {
		var parse *d2parser.ParseError
		if errors.As(err, &parse) {
			for _, e := range parse.Errors {
				out.Diagnostics = append(out.Diagnostics, diagnostic{"d2-compile", e.Message, e.Range.Path, e.Range.Start.Line + 1, e.Range.Start.Column + 1})
			}
		} else {
			out.Diagnostics = append(out.Diagnostics, diagnostic{Code: "d2-compile", Message: err.Error()})
		}
	}
	for name, saved := range s.files {
		hash := sha256.Sum256(saved.data)
		out.Inputs = append(out.Inputs, input{name, hex.EncodeToString(hash[:])})
	}
	sort.Slice(out.Inputs, func(i, j int) bool { return out.Inputs[i].File < out.Inputs[j].File })
	out.OK = err == nil
	return out
}
func main() {
	version := flag.Bool("version", false, "print protocol and upstream identity as JSON")
	root := flag.String("root", ".", "project root; imports cannot escape it")
	entry := flag.String("input", "", "project-relative D2 file")
	flag.Parse()
	if *version {
		json.NewEncoder(os.Stdout).Encode(result{Protocol: protocol, D2: upstream, Revision: revision, OK: true})
		return
	}
	if *entry == "" {
		fmt.Fprintln(os.Stderr, "--input is required")
		os.Exit(2)
	}
	abs, err := filepath.Abs(*root)
	if err == nil {
		abs, err = filepath.EvalSymlinks(abs)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	out := compile(abs, filepath.ToSlash(*entry))
	if err := json.NewEncoder(os.Stdout).Encode(out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if !out.OK {
		os.Exit(1)
	}
}
