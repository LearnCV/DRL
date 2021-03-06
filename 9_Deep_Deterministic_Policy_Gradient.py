# Deep Deterministic Policy Gradient Algorithm

# Import modules
import tensorflow as tf
import pygame
import random
import numpy as np
import matplotlib.pyplot as plt
import datetime
import time
import cv2
import os

# Import game
import sys
sys.path.append("DQN_GAMES_Policy/")

import Deep_Parameters

import breakout as game

class DDPG:
	def __init__(self):

		# Game Information
		self.algorithm = 'DDPG'
		self.game_name = game.ReturnName()

		# Get parameters
		self.progress = ''
		self.Num_action = game.Return_Num_Action()
		self.Action_bound = game.Return_Action_Bound()

		# Initial parameters
		self.Num_Exploration = 100
		# self.Num_Exploration = Deep_Parameters.Num_start_training
		self.Num_Training    = Deep_Parameters.Num_training
		self.Num_Testing     = Deep_Parameters.Num_test

		self.learning_rate_actor  = 0.001
		self.learning_rate_critic = 0.0001
		self.gamma = Deep_Parameters.Gamma

		self.first_epsilon = Deep_Parameters.Epsilon
		self.final_epsilon = Deep_Parameters.Final_epsilon

		self.epsilon = self.first_epsilon

		self.Num_plot_episode = Deep_Parameters.Num_plot_episode

		self.Is_train = Deep_Parameters.Is_train
		self.load_path = Deep_Parameters.Load_path

		self.step = 1
		self.score = 0
		self.episode = 0

		# date - hour - minute of training time
		self.date_time = str(datetime.date.today()) + '_' + \
		                 str(datetime.datetime.now().hour) + '_' + \
						 str(datetime.datetime.now().minute)

		# parameters for skipping and stacking
		self.state_set = []
		self.Num_skipping = Deep_Parameters.Num_skipFrame
		self.Num_stacking = Deep_Parameters.Num_stackFrame

		# Parameter for Experience Replay
		self.Num_replay_memory = Deep_Parameters.Num_replay_memory
		self.Num_batch = Deep_Parameters.Num_batch
		self.replay_memory = []

		# Parameter for Target Network
		self.tau = 0.001

		# Parameters for network
		self.img_size = 80
		self.Num_colorChannel = Deep_Parameters.Num_colorChannel

		self.first_conv   = Deep_Parameters.first_conv
		self.second_conv  = Deep_Parameters.second_conv
		self.third_conv   = Deep_Parameters.third_conv
		self.first_dense  = Deep_Parameters.first_dense
		self.dense_actor  = [self.first_dense[1], self.Num_action]
		self.dense_critic = [self.first_dense[1] + self.Num_action, 1]

		self.GPU_fraction = Deep_Parameters.GPU_fraction

		# Variables for Ornstein-Uhlenbeck Process
		self.mu_UL = 0
		self.x_UL = 0
		self.theta_UL = 0.15
		self.sigma_UL = 0.3

		# Variables for tensorboard
		self.loss = 0
		self.maxQ = 0
		self.score_board = 0
		self.maxQ_board  = 0
		self.loss_board  = 0
		self.step_old    = 0

		# Initialize Network
		self.input_actor, self.output_actor, self.net_vars_actor = self.Actor('network')
		self.input_critic, self.action_critic, self.output_critic = self.Critic('network')
		self.input_target_actor, self.output_target_actor, _ = self.Actor('target')
		self.input_target_critic, self.action_target_critic, self.output_target_critic = self.Critic('target')

		self.train_step_actor, self.train_step_critic, self.y_target, self.loss_train, self.grad_Q_action = self.loss_and_train()
		self.sess, self.saver, self.summary_placeholders, self.update_ops, self.summary_op, self.summary_writer = self.init_sess()

	def main(self):
		# Define game state
		game_state = game.GameState()

		# Initialization
		state = self.initialization(game_state)
		stacked_state = self.skip_and_stack_frame(state)

		while True:
			# Get progress:
			self.progress = self.get_progress()

			# Select action
			action = self.select_action(stacked_state)

			# Take action and get info. for update
			next_state, reward, terminal = game_state.frame_step(self.Action_bound * action)
			next_state = self.reshape_input(next_state)
			stacked_next_state = self.skip_and_stack_frame(next_state)

			# Experience Replay
			self.experience_replay(stacked_state, action, reward, stacked_next_state, terminal)

			# Training!
			if self.progress == 'Training':
				# Update target network
				# if self.step % self.Num_update_target == 0:
				# self.update_target()

				# Training
				self.train(self.replay_memory)

				# Save model
				self.save_model()

			# Update former info.
			stacked_state = stacked_next_state
			self.score += reward
			self.step += 1

			# Plotting
			self.plotting(terminal)

			# If game is over (terminal)
			if terminal:
				stacked_state = self.if_terminal(game_state)

			# Finished!
			if self.progress == 'Finished':
				print('Finished!')
				break

	def init_sess(self):
		# Initialize variables
		config = tf.ConfigProto()
		config.gpu_options.per_process_gpu_memory_fraction = self.GPU_fraction

		sess = tf.InteractiveSession(config=config)

		# Make folder for save data
		os.makedirs('saved_networks_PG/' +
		             self.game_name + '/' +
					 self.date_time + '_' +
					 self.algorithm)

		# Summary for tensorboard
		summary_placeholders, update_ops, summary_op = self.setup_summary()
		summary_writer = tf.summary.FileWriter('saved_networks_PG/' +
												self.game_name + '/' +
												self.date_time + '_' +
												self.algorithm, sess.graph)

		init = tf.global_variables_initializer()
		sess.run(init)

		# Load the file if the saved file exists
		saver = tf.train.Saver()
		# check_save = 1
		check_save = input('Load Model? (1=yes/2=no): ')

		if check_save == 1:
			# Restore variables from disk.
			saver.restore(sess, self.load_path + "/model.ckpt")
			print("Model restored.")

			check_train = input('Inference or Training? (1=Inference / 2=Training): ')
			if check_train == 1:
				self.Num_Exploration = 0
				self.Num_Training = 0

		return sess, saver, summary_placeholders, update_ops, summary_op, summary_writer

	def initialization(self, game_state):
		action = np.zeros([self.Num_action])
		state, _, _ = game_state.frame_step(action)
		state = self.reshape_input(state)

		for i in range(self.Num_skipping * self.Num_stacking):
			self.state_set.append(state)

		return state

	def skip_and_stack_frame(self, state):
		self.state_set.append(state)

		state_in = np.zeros((self.img_size, self.img_size, self.Num_colorChannel * self.Num_stacking))

		# Stack the frame according to the number of skipping frame
		for stack_frame in range(self.Num_stacking):
			state_in[:,:,stack_frame] = self.state_set[-1 - (self.Num_skipping * stack_frame)]

		del self.state_set[0]

		state_in = np.uint8(state_in)
		return state_in

	def get_progress(self):
		progress = ''
		if self.step <= self.Num_Exploration:
			progress = 'Exploring'
		elif self.step <= self.Num_Exploration + self.Num_Training:
			progress = 'Training'
		elif self.step <= self.Num_Exploration + self.Num_Training + self.Num_Testing:
			progress = 'Testing'
		else:
			progress = 'Finished'

		return progress

	# Resize and make input as grayscale
	def reshape_input(self, state):
		state_out = cv2.resize(state, (self.img_size, self.img_size))
		if self.Num_colorChannel == 1:
			state_out = cv2.cvtColor(state_out, cv2.COLOR_BGR2GRAY)
			state_out = np.reshape(state_out, (self.img_size, self.img_size))

		state_out = np.uint8(state_out)

		return state_out

	# Code for tensorboard
	def setup_summary(self):
	    episode_score = tf.Variable(0.)
	    episode_maxQ = tf.Variable(0.)
	    episode_loss = tf.Variable(0.)

	    tf.summary.scalar('Average Score/' + str(self.Num_plot_episode) + ' episodes', episode_score)
	    tf.summary.scalar('Average MaxQ/' + str(self.Num_plot_episode) + ' episodes', episode_maxQ)
	    tf.summary.scalar('Average Loss/' + str(self.Num_plot_episode) + ' episodes', episode_loss)

	    summary_vars = [episode_score, episode_maxQ, episode_loss]

	    summary_placeholders = [tf.placeholder(tf.float32) for _ in range(len(summary_vars))]
	    update_ops = [summary_vars[i].assign(summary_placeholders[i]) for i in range(len(summary_vars))]
	    summary_op = tf.summary.merge_all()
	    return summary_placeholders, update_ops, summary_op

	# Convolution and pooling
	def conv2d(self, x, w, stride):
		return tf.nn.conv2d(x,w,strides=[1, stride, stride, 1], padding='SAME')

	# Get Variables
	def conv_weight_variable(self, name, shape):
	    return tf.get_variable(name, shape = shape, initializer = tf.contrib.layers.xavier_initializer_conv2d())

	def weight_variable(self, name, shape):
	    return tf.get_variable(name, shape = shape, initializer = tf.contrib.layers.xavier_initializer())

	def bias_variable(self, name, shape):
	    return tf.get_variable(name, shape = shape, initializer = tf.contrib.layers.xavier_initializer())

	def Actor(self, network_name):
		# Input
		x_image = tf.placeholder(tf.float32, shape = [None,
													  self.img_size,
													  self.img_size,
													  self.Num_stacking * self.Num_colorChannel])

		x_normalize = (x_image - (255.0/2)) / (255.0/2)

		with tf.variable_scope(network_name):
			# Convolution variables
			w_conv1 = self.conv_weight_variable('_actor_w_conv1' + network_name, self.first_conv)
			b_conv1 = self.bias_variable('_actor_b_conv1' + network_name,[self.first_conv[3]])

			w_conv2 = self.conv_weight_variable('_actor_w_conv2' + network_name,self.second_conv)
			b_conv2 = self.bias_variable('_actor_b_conv2' + network_name,[self.second_conv[3]])

			w_conv3 = self.conv_weight_variable('_actor_w_conv3' + network_name,self.third_conv)
			b_conv3 = self.bias_variable('_actor_b_conv3' + network_name,[self.third_conv[3]])

			# Densely connect layer variables
			w_fc1 = self.weight_variable('_actor_w_fc1' + network_name,self.first_dense)
			b_fc1 = self.bias_variable('_actor_b_fc1' + network_name,[self.first_dense[1]])

			w_fc2 = self.weight_variable('_actor_w_fc2' + network_name,self.dense_actor)
			b_fc2 = self.bias_variable('_actor_b_fc2' + network_name,[self.dense_actor[1]])

		# Network
		h_conv1 = tf.nn.relu(self.conv2d(x_normalize, w_conv1, 4) + b_conv1)
		h_conv2 = tf.nn.relu(self.conv2d(h_conv1, w_conv2, 2) + b_conv2)
		h_conv3 = tf.nn.relu(self.conv2d(h_conv2, w_conv3, 1) + b_conv3)

		h_pool3_flat = tf.reshape(h_conv3, [-1, self.first_dense[0]])
		h_fc1 = tf.nn.relu(tf.matmul(h_pool3_flat, w_fc1)+b_fc1)

		output = tf.tanh(tf.matmul(h_fc1, w_fc2) + b_fc2)

		network_variables = tf.trainable_variables()

		return x_image, output, network_variables

	def Critic(self, network_name):
		# Input
		x_image = tf.placeholder(tf.float32, shape = [None,
													  self.img_size,
													  self.img_size,
													  self.Num_stacking * self.Num_colorChannel])

		x_normalize = (x_image - (255.0/2)) / (255.0/2)

		# x_action = tf.placeholder(tf.float32, shape = [None,self.Num_action])
		x_action = tf.placeholder(tf.float32, shape = [None, self.Num_action])

		with tf.variable_scope(network_name):
			# Convolution variables
			w_conv1 = self.conv_weight_variable(network_name + '_critic_w_conv1', self.first_conv)
			b_conv1 = self.bias_variable(network_name + '_critic_b_conv1',[self.first_conv[3]])

			w_conv2 = self.conv_weight_variable(network_name + '_critic_w_conv2',self.second_conv)
			b_conv2 = self.bias_variable(network_name + '_critic_b_conv2',[self.second_conv[3]])

			w_conv3 = self.conv_weight_variable(network_name + '_critic_w_conv3',self.third_conv)
			b_conv3 = self.bias_variable(network_name + '_critic_b_conv3',[self.third_conv[3]])

			# Densely connect layer variables
			w_fc1 = self.weight_variable(network_name + '_critic_w_fc1',self.first_dense)
			b_fc1 = self.bias_variable(network_name + '_critic_b_fc1',[self.first_dense[1]])

			w_fc2 = self.weight_variable(network_name + '_critic_w_fc2',self.dense_critic)
			b_fc2 = self.bias_variable(network_name + '_critic_b_fc2',[self.dense_critic[1]])

		# Network
		h_conv1 = tf.nn.relu(self.conv2d(x_normalize, w_conv1, 4) + b_conv1)
		h_conv2 = tf.nn.relu(self.conv2d(h_conv1, w_conv2, 2) + b_conv2)
		h_conv3 = tf.nn.relu(self.conv2d(h_conv2, w_conv3, 1) + b_conv3)

		h_pool3_flat = tf.reshape(h_conv3, [-1, self.first_dense[0]])
		h_fc1 = tf.nn.relu(tf.matmul(h_pool3_flat, w_fc1)+b_fc1)
		h_fc1 = tf.concat([h_fc1, x_action], axis = 1)

		output = tf.matmul(h_fc1, w_fc2) + b_fc2
		return x_image, x_action, output

	def loss_and_train(self):
		# Loss function and Train
		y_target = tf.placeholder(tf.float32, shape = [None])
		grad_Q = tf.placeholder(tf.float32,[None, self.Num_action])
		Loss_critic = tf.reduce_mean(tf.square(tf.subtract(y_target, self.output_critic)))

		# grad_Q_action = tf.gradients(self.output_critic, self.output_actor)
		grad_J_actor  = tf.gradients(self.output_actor, self.net_vars_actor, -grad_Q[0])

		# Get trainable variables
		trainable_variables = tf.trainable_variables()

		# network variables
		trainable_variables_network_actor = [var for var in trainable_variables if var.name.startswith('network_actor')]
		trainable_variables_network_critic = [var for var in trainable_variables if var.name.startswith('network_critic')]

		opt_actor  = tf.train.AdamOptimizer(learning_rate = self.learning_rate_actor, epsilon = 1e-02)
		opt_critic = tf.train.AdamOptimizer(learning_rate = self.learning_rate_critic, epsilon = 1e-02)

		train_step_critic = opt_critic.minimize(Loss_critic)
		train_step_actor  = opt_actor.apply_gradients(zip(grad_J_actor,self.net_vars_actor))

		return train_step_actor, train_step_critic, y_target, Loss_critic, grad_Q

	def select_action(self, stacked_state):
		# Choose action
		if self.progress == 'Exploring':
			# Choose random action
			action = np.random.uniform(-1.0, 1.0, self.Num_action)

			# Do Orstein-Uhlenbeck Process
			action_actor = self.output_actor.eval(feed_dict={self.input_actor: [stacked_state]})
			noise_UL = self.theta_UL * (self.mu_UL - action_actor) + self.sigma_UL * np.random.randn(self.Num_action)
			action = action_actor + noise_UL
			np.clip(action, -1.0, 1.0)
			action = np.reshape(action, (self.Num_action))

		elif self.progress == 'Training':
			# Do Orstein-Uhlenbeck Process
			action_actor = self.output_actor.eval(feed_dict={self.input_actor: [stacked_state]})
			noise_UL = self.theta_UL * (self.mu_UL - action_actor) + self.sigma_UL * np.random.randn(self.Num_action)
			critic_test = self.output_critic.eval(feed_dict={self.input_critic: [stacked_state], self.action_critic: action_actor})
			print('action_actor: ' + str(action_actor))
			print('noise_UL: ' + str(noise_UL))
			action = action_actor + noise_UL
			np.clip(action, -1.0, 1.0)
			action = np.reshape(action, (self.Num_action))

		elif self.progress == 'Testing':
			# Use actor's output as action
			action_actor = self.output_actor.eval(feed_dict={self.input_actor: [stacked_state]})
			action = action_actor

		return action

	def experience_replay(self, state, action, reward, next_state, terminal):
		# If Replay memory is longer than Num_replay_memory, delete the oldest one
		if len(self.replay_memory) >= self.Num_replay_memory:
			del self.replay_memory[0]

		self.replay_memory.append([state, action, reward, next_state, terminal])

	def update_target(self):
		# Get trainable variables
		trainable_variables = tf.trainable_variables()
		# network variables
		trainable_vars_net_actor  = [var for var in trainable_variables if var.name.startswith('network_actor')]
		trainable_vars_net_critic = [var for var in trainable_variables if var.name.startswith('network_critic')]

		# target variables
		trainable_vars_tar_actor  = [var for var in trainable_variables if var.name.startswith('target_actor')]
		trainable_vars_tar_critic = [var for var in trainable_variables if var.name.startswith('target_critic')]

		for i in range(len(trainable_vars_net_actor)):
			self.sess.run(tf.assign(trainable_vars_tar_actor[i],
			                        self.tau * trainable_vars_net_actor[i] + (1-self.tau) * trainable_vars_tar_actor[i]))

			self.sess.run(tf.assign(trainable_vars_tar_critic[i],
			                        self.tau * trainable_vars_net_critic[i] + (1-self.tau) * trainable_vars_tar_critic[i]))

	def train(self, replay_memory):
		# Select minibatch
		minibatch =  random.sample(replay_memory, self.Num_batch)

		# Save the each batch data
		state_batch      = [batch[0] for batch in minibatch]
		action_batch     = [batch[1] for batch in minibatch]
		reward_batch     = [batch[2] for batch in minibatch]
		next_state_batch = [batch[3] for batch in minibatch]
		terminal_batch   = [batch[4] for batch in minibatch]

		# Get y_prediction
		y_batch = []

		next_output_actor_batch = self.output_target_actor.eval(feed_dict = {self.input_target_actor: next_state_batch})
		Q_batch = self.output_target_critic.eval(feed_dict = {self.input_target_critic: next_state_batch,
														      self.action_target_critic: next_output_actor_batch})


		output_actor_batch = self.output_actor.eval(feed_dict = {self.input_actor: state_batch})
		output_critic_batch = self.output_critic.eval(feed_dict = {self.input_critic: state_batch, self.action_critic: output_actor_batch})

		grad_Q_tmp = tf.gradients(output_critic_batch, output_actor_batch)
		grad_Q_tmp = np.reshape(grad_Q_tmp, (-1,1))

		# Get target values
		for i in range(len(minibatch)):
			if terminal_batch[i] == True:
				y_batch.append(reward_batch[i])
			else:
				y_batch.append(reward_batch[i] + self.gamma * np.max(Q_batch[i]))

		_, _, self.loss = self.sess.run([self.train_step_actor, self.train_step_critic, self.loss_train],
		                                 feed_dict = {self.y_target: y_batch,
										 			  self.input_actor: state_batch,
													  self.input_critic: state_batch,
													  self.action_critic: output_actor_batch,
													  self.grad_Q_action: grad_Q_tmp})

	def save_model(self):
		# Save the variables to disk.
		if self.step == self.Num_Exploration + self.Num_Training:
		    save_path = self.saver.save(self.sess, 'saved_networks_PG/' + self.game_name + '/' + self.date_time + '_' + self.algorithm + "/model.ckpt")
		    print("Model saved in file: %s" % save_path)

	def plotting(self, terminal):
		if self.progress != 'Exploring':
			if terminal:
				self.score_board += self.score

			self.maxQ_board  += self.maxQ
			self.loss_board  += self.loss

			if self.episode % self.Num_plot_episode == 0 and self.episode != 0 and terminal:
				diff_step = self.step - self.step_old
				tensorboard_info = [self.score_board / self.Num_plot_episode, self.maxQ_board / diff_step, self.loss_board / diff_step]

				for i in range(len(tensorboard_info)):
				    self.sess.run(self.update_ops[i], feed_dict = {self.summary_placeholders[i]: float(tensorboard_info[i])})
				summary_str = self.sess.run(self.summary_op)
				self.summary_writer.add_summary(summary_str, self.step)

				self.score_board = 0
				self.maxQ_board  = 0
				self.loss_board  = 0
				self.step_old = self.step
		else:
			self.step_old = self.step

	def if_terminal(self, game_state):
		# Show Progress
		print('Step: ' + str(self.step) + ' / ' +
		      'Episode: ' + str(self.episode) + ' / ' +
			  'Progress: ' + self.progress + ' / ' +
			  'Epsilon: ' + str(self.epsilon) + ' / ' +
			  'Score: ' + str(self.score))

		if self.progress != 'Exploring':
			self.episode += 1
		self.score = 0

		# If game is finished, initialize the state
		state = self.initialization(game_state)
		stacked_state = self.skip_and_stack_frame(state)

		return stacked_state

if __name__ == '__main__':
	agent = DDPG()
	agent.main()
