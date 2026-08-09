{
  description = "Strict Python + uv.lock + Nix (uv2nix)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config = {
            allowUnfree = true;

          };
        };
        lib = pkgs.lib;
        python = pkgs.python312;

        workspace = uv2nix.lib.workspace.loadWorkspace {
          workspaceRoot = ./.;
        };

        projectOverlay = workspace.mkPyprojectOverlay {
          sourcePreference = "wheel";
        };

        pyPkgs = (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope (
          lib.composeManyExtensions [
            pyproject-build-systems.overlays.default
            projectOverlay
            (final: prev: { })
          ]
        );

        venv = pyPkgs.mkVirtualEnv "ctxbench-venv" {
          ctxbench = [ "dev" ];
        };

        ctxbenchPkg = pkgs.symlinkJoin {
          name = "llmctxbench";
          paths = [ venv ];
          nativeBuildInputs = [ pkgs.makeWrapper ];
          postBuild = ''
            if [ -e "$out/bin/llmctxbench" ]; then
              rm "$out/bin/llmctxbench"
            fi
            makeWrapper "${venv}/bin/python" "$out/bin/llmctxbench" \
              --prefix PYTHONPATH : "${./src}" \
              --add-flags "-m" \
              --add-flags "ctxbench.cli"
          '';
        };

      in
      {
        packages.default = ctxbenchPkg;

        apps.default = {
          type = "app";
          program = "${ctxbenchPkg}/bin/llmctxbench";
        };

        devShells.default = pkgs.mkShell {
          packages = [
            venv
            pkgs.pyright
            pkgs.ruff
            pkgs.uv
            pkgs.git
            pkgs.codex
            pkgs.claude-code
            pkgs.duckdb
          ];

          shellHook = ''
            export REPO_ROOT="$(pwd)"
            export PYTHONPATH="$REPO_ROOT/src"
            export VIRTUAL_ENV="${venv}"
            export PATH="${venv}/bin:${ctxbenchPkg}/bin:$PATH"

            # opcional: ajuda plugins que procuram uma pasta .venv no projeto
            if [ -L .venv ] || [ ! -e .venv ]; then
              ln -sfn "${venv}" .venv
            else
              echo "warning: .venv exists and is not a symlink; not replacing it"
            fi

            echo "llmctxbench dev shell ready (from uv.lock)."
            echo "Python: $(which python)"
            python -m debugpy --version || true
          '';
        };
      }
    );
}
