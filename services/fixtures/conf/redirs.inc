    # 12-hop chain used by sandbox tests: /redir/1 -> ... -> /redir/12 (the cap is 10 redirects)
    location = /redir/1 { return 302 /redir/2; }
    location = /redir/2 { return 302 /redir/3; }
    location = /redir/3 { return 302 /redir/4; }
    location = /redir/4 { return 302 /redir/5; }
    location = /redir/5 { return 302 /redir/6; }
    location = /redir/6 { return 302 /redir/7; }
    location = /redir/7 { return 302 /redir/8; }
    location = /redir/8 { return 302 /redir/9; }
    location = /redir/9 { return 302 /redir/10; }
    location = /redir/10 { return 302 /redir/11; }
    location = /redir/11 { return 302 /redir/12; }
    location = /redir/12 { default_type text/plain; return 200 "end of chain (test fixture)\n"; }
    location = /redir/short { return 302 /redir/11; }
