# Poor person's test. Execute from the root directory of the repo with
#
#   python -m website.tests.test
#
# If the script terminates normally, without throwing an exception, everything is fine.

import json
import numpy as np
from numpy.random import uniform

from ftm.core.utils import *
from ftm.core.model import *
from ftm.analysis.mc_analysis import TakeoffParamsDist

parser = init_cli_arguments()
args = handle_cli_arguments(parser)

MODULE_DIR = os.path.dirname(os.path.realpath(__file__))

js_model_path = os.path.join(MODULE_DIR, '../src/js/ftm')

parameter_table = get_parameter_table()
best_guess_parameters   = {parameter : row['Best guess']   for parameter, row in parameter_table.iterrows()}
aggressive_parameters   = {parameter : row['Aggressive']   for parameter, row in parameter_table.iterrows()}
conservative_parameters = {parameter : row['Conservative'] for parameter, row in parameter_table.iterrows()}

class JSModel:
  def __init__(self, project_path):
    from py_mini_racer import MiniRacer

    scripts = [
      'nj.js',
      'ftm.js',
      'bridge.js',
    ]

    ctx = MiniRacer()
    for script in scripts:
      with open(os.path.join(project_path, script), 'r') as f:
        script = f.read()
        ctx.eval(script)

    self.module = ctx

  def simulate(self, parameters):
    self.parameters = parameters
    self.module.eval('''
      log = [];
      console = {log: function() {
        log.push(Array.from(arguments).map(x => JSON.stringify(x)).join(', '));
      }};
    ''')
    self.module.eval(f'simulation_result = ftm.run_simulation(bridge.transform_python_to_js_params({json.dumps(self.parameters)}))')
    print(self.module.execute("log.join('\\n')"))

  def __getattr__(self, key):
    keys = self.eval_and_get('Reflect.ownKeys(simulation_result).concat(Reflect.ownKeys(Reflect.getPrototypeOf(simulation_result)))')
    if key in keys:
      t = self.eval_and_get(f'typeof simulation_result.{key}')
      if t == 'function':
        return lambda: self.eval_and_get(f'simulation_result.{key}()')
      else:
        return self.eval_and_get(f'simulation_result.{key}')
    else:
      return self.eval_and_get(f'simulation_result.get_thread("{key}")')

  def eval_and_get(self, expression):
    self.module.eval(f'foo = () => {expression}')
    return self.module.call('foo')


def compare(params):
  # Run Js model
  js_model = JSModel(js_model_path)
  js_model.simulate(params)

  js_summary_table = js_model.get_summary_table()
  js_takeoff_metrics = js_model.get_takeoff_metrics()

  # Run Python model
  python_model = SimulateTakeOff(**params)
  python_model.run_simulation()

  python_summary_table = python_model.get_summary_table().to_dict(orient = 'list')
  python_takeoff_metrics = python_model.get_takeoff_metrics().to_dict(orient = 'list')

  # Compare results

  eps = 1e-7

  def assert_roughly_equal(v, w):
    print(v, w)
    if isinstance(v, (list, tuple)):
      assert(len(v) == len(w))
      for i in range(len(v)): assert_roughly_equal(v[i], w[i])
      return

    if isinstance(v, str): assert(v == w)
    elif v is None or np.isnan(v): assert(w is None or np.isnan(w))
    elif w is None or np.isnan(w): assert(v is None or np.isnan(v))
    elif abs(v) > eps: assert (abs(w - v)/v < eps), (v, w)
    else: assert (abs(w - v) < eps)

  def compare_tables(a, b):
    assert(a.keys() == b.keys()), (a.keys(), b.keys())
    for k in a:
      v = a[k]
      w = b[k]
      if isinstance(v, (list, tuple)):
        assert(len(v) == len(w))
        print(k, v, w)
        if k == 'doubling times':
          # Sorry about this
          fields_v = v[0]
          fields_w = w[0]

          if isinstance(fields_v, str): fields_v = fields_v[1:][:-1].split(', ')
          if isinstance(fields_w, str): fields_w = fields_w[1:][:-1].split(', ')

          print(fields_v, fields_w)
          assert(len(fields_v) == len(fields_w))
          for i in range(len(fields_v)): assert_roughly_equal(float(fields_v[i]), float(fields_w[i]))
        else:
          for i in range(len(v)): assert_roughly_equal(v[i], w[i])
      else:
        assert_roughly_equal(v, w)

  assert('doubling_times' in js_takeoff_metrics)

  js_takeoff_metrics['doubling times'] = [js_takeoff_metrics['doubling_times'][0][:4]]
  del js_takeoff_metrics['doubling_times']

  # Transform to Python notation
  period = js_summary_table['period']
  for i, p in enumerate(period):
    period[i] = {
      'Pre wake-up': 'prerampup',
      'Wake-up': 'rampup start',
      'Mid rampup': 'mid rampup',
      'Full economic automation': 'full economic automation',
    }[p]

  compare_tables(python_summary_table, js_summary_table)
  compare_tables(python_takeoff_metrics, js_takeoff_metrics)

  print("All good!!")

params_dist = TakeoffParamsDist()

for i in range(100):
  sample = params_dist.rvs(1)
  params = {param: sample[param][0] for param in sample}
  params['t_step'] = 1
  params['initial_population'] = 10**uniform(3, 12)
  params['initial_buyable_hardware_performance'] = 10**uniform(14, 16)
  params['training_requirements_steepness'] = uniform(0, 10)
  params['runtime_requirements_steepness'] = uniform(0, 40)
  #params['runtime_training_tradeoff'] = 10
  #params['runtime_training_max_tradeoff'] = 100
  print(params)
  compare(params)
