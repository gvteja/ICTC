# _*_ coding:utf-8 _*_
import cherrypy
import atexit
import sqlite3
import threading
import time

con = None
pairs = {}
long_txt = 'wae rawg est st h r dt hry  jtfjjt j tyjf tj tk ugy agr re g esg se g tsh rdryhdtd dh drt h ht h thfyj ftj   s e  esh srt hd  ht  a efw  fw rg e  g '
for i in range(12):
    s = str(i)
    b = 't' if (i/3) % 2 else 'c'
    pair = [i, i/3, b, 'inp' + s + long_txt, 'r1_'+ s + long_txt, 'r2_' + s + long_txt]
    pairs[i] = pair

next_user_id = '1'
user_data = {}
waiting_lock = threading.Lock()
backlog_lock = threading.Lock()
user_lock = threading.Lock() # modifying user data/ next_user_id
backlog = pairs.keys()
waiting = []
time_limit = 1 * 60

@atexit.register
def cleanup():
    global con
    if con:
        con.close()
        con = None
        cherrypy.log('Closed DB connection')
    cherrypy.log('Finished cleanup')


class ICTC(object):

    @cherrypy.expose
    def index(self):
        global next_user_id
        request_cookie = cherrypy.request.cookie
        response_cookie = cherrypy.response.cookie
        cookies = {}
        if 'user_id' not in request_cookie:
            # new user, assign a new user_id
            with user_lock:
                user_id = next_user_id
                cookies['user_id'] = user_id
                next_user_id = str(int(next_user_id) + 1)
                user_data[user_id] = set()
        else:
            user_id = request_cookie['user_id'].value
        order_id = self.getPair(user_id)
        _, _, bot, input_text, response1, response2 = pairs[order_id]
        cookies.update({
            'order_id': order_id,
            'bot' : bot,
            'input': input_text,
            'response1': response1,
            'response2': response2
        })
        for name, value in cookies.iteritems():
            response_cookie[name] = value
            response_cookie[name]['path'] = '/'
            response_cookie[name]['max-age'] = 3600 ** 5
            response_cookie[name]['version'] = 1
        return client_html

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def getPair(self, user_id):
        #print 'Get pair', user_data
        global backlog
        selected_id = None
        now = time.time()
        with waiting_lock:
            #print user_id, waiting
            for waiting_data in waiting:
                ts, order_id, waiting_user = waiting_data
                if user_id == waiting_user:
                    # this pair was served to the current user
                    # but has not been answered yet
                    # so serve it again
                    selected_id = order_id
                    #print 'serving again', waiting_data
                elif ts + time_limit > now:
                    # need to serve order_id this to user
                    true_id = pairs[order_id][1]
                    if true_id in user_data[user_id]:
                        # user has already answered this q
                        # so skip it
                        #print 'skipping q', waiting_data
                        continue
                    else:
                        selected_id = order_id
                        #print 'serving coz of time', waiting_data
                else:
                    #print 'no condition satisfied', waiting_data
                    pass
                if selected_id:
                    # update waiting data with time and user_id
                    waiting_data[0] = now
                    waiting_data[2] = user_id
                    break

        if selected_id != None:
            self.writeToServeDB(selected_id, user_id, cherrypy.request.remote.ip)
            return selected_id
        # else return pair with lowest (unanswered) order id
        #print 'taking from backlog', selected_id
        with backlog_lock:
            backlog.sort()
            answered = user_data[user_id]
            for order_id in backlog:
                true_id = pairs[order_id][1]
                if true_id not in answered:
                    selected_id = order_id
                    #print 'true_id {0} not in {1}'.format(true_id, answered)
                    break
                else:
                    #print 'true_id {0} in {1}'.format(true_id, answered)
                    pass
            # remove pair from backlog
            backlog = [order_id for order_id in backlog if order_id != selected_id]
        # add timestamp and put in waiting q
        with waiting_lock:
            waiting.append([now, selected_id, user_id])
        self.writeToServeDB(selected_id, user_id, cherrypy.request.remote.ip)
        return selected_id

    def writeToServeDB(self, order_id, user_id, ip):
        values = [
            order_id,
            user_id,
            ip
        ]
        con.execute('insert into Serve(order_id, user_id, ip) values(?, ?, ?)', values)

    @cherrypy.expose
    @cherrypy.tools.json_out()
    @cherrypy.tools.json_in()
    def feedback(self):
        global waiting
        #print 'Feedback', user_data
        feedback_data = cherrypy.request.json
        user_id = feedback_data['user_id']
        order_id = int(feedback_data['order_id'])
        _, true_id, bot, input_text, response1, response2 = pairs[order_id]
        user_data[user_id].add(true_id)
                
        with waiting_lock:
            # remove pair from waiting
            waiting = [pair for pair in waiting if pair[1] != order_id]

        values = [
            bot,
            input_text,
            response1,
            response2,
            feedback_data['content_score1'],
            feedback_data['content_score2'],
            feedback_data['style_score1'],
            feedback_data['style_score2'],
            feedback_data['comparision'],
            user_id,
            cherrypy.request.remote.ip
        ]
        con.execute('insert into Feedback(bot, input, response1, response2, content_score1, content_score2, style_score1, style_score2, comparision, user_id, ip) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', values)

        return True


if __name__ == '__main__':
    home_dir = '/Users/bobby/Downloads'
    #home_dir = '/home/stufs1/vgottipati'

    con = sqlite3.connect(
        home_dir + '/comparision.db', 
        isolation_level=None, 
        check_same_thread=False)
    con.execute("create table if not exists Feedback(bot TEXT, input TEXT, response1 TEXT, response2 TEXT, content_score1 INTEGER NOT NULL, content_score2 INTEGER NOT NULL, style_score1 INTEGER NOT NULL, style_score2 INTEGER NOT NULL, comparision INTEGER NOT NULL, suggestion TEXT, user_id TEXT, ip TEXT, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)")
    con.execute("create table if not exists Serve(order_id INTEGER, user_id TEXT, ip TEXT, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)")

    cherrypy.engine.subscribe('stop', cleanup)

    app_conf = {
        '/': {
            'tools.staticdir.on'            : True,
            'tools.staticdir.dir'           : home_dir + '/Static'
        }
    }

    cherrypy.config.update({
        'server.socket_host': '0.0.0.0',
        'server.socket_port': 8080,
        'log.screen': False,
        'log.access_file': home_dir + '/server_access.log',
        'log.error_file': home_dir + '/server_error.log'
                       })

    client_html = ''
    with open(home_dir + '/Static/ictc.html', 'r') as client_html_file:
        client_html = client_html_file.read()

    try:
        cherrypy.quickstart(ICTC(), '/', app_conf)
    except:
        cleanup()
        raise